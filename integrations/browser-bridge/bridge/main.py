"""Local Browser Bridge application entrypoint.

Security model (from the AATM spec, always on):
  * The bridge binds to the loopback interface by default (``BRIDGE_HOST``).
  * Every WebSocket handshake validates the ``Origin`` header (protection against
    cross-site WebSocket hijacking).
  * Every WebSocket handshake requires a paired credential (``BRIDGE_PAIR_TOKEN``)
    that matches the owner's paired userscript.

The endpoint exposes ``/health`` for the Docker healthcheck and ``/ws`` for the
userscript transport.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

APP_VERSION = os.getenv("APP_VERSION", "0.1.0")

# Default set of origins allowed to open the WebSocket. The owner can extend or
# override this with BRIDGE_ALLOWED_ORIGINS (comma-separated).
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:8080,http://127.0.0.1:8080"
)


def _allowed_origins() -> set[str]:
    raw = os.getenv("BRIDGE_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    return {origin.strip() for origin in raw.split(",") if origin.strip()}


def _expected_token() -> str:
    return os.getenv("BRIDGE_PAIR_TOKEN", "")


app = FastAPI(
    title="NEXUS AGENT OS Local Browser Bridge",
    version=APP_VERSION,
    description="Local bridge between the userscript and the backend.",
)


def _health_payload(service: str) -> dict[str, str]:
    return {
        "status": "ok",
        "service": service,
        "version": APP_VERSION,
        "time": datetime.now(UTC).isoformat(),
    }


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness/readiness probe for the bridge."""
    return _health_payload("bridge")


def _is_origin_allowed(origin: str) -> bool:
    allowed = _allowed_origins()
    # No configured origins means no origin is trusted.
    return origin in allowed if allowed else False


@app.websocket("/ws")
async def ws_endpoint(
    websocket: WebSocket,
    token: str = Query(default="", description="Paired credential"),
) -> None:
    """Userscript transport.

    The handshake is rejected (HTTP 403) before the upgrade when the origin is
    not trusted or the pair credential does not match.
    """
    origin = websocket.headers.get("origin", "")
    if not _is_origin_allowed(origin):
        await websocket.close(code=1008)
        return

    expected = _expected_token()
    if not expected or token != expected:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_json({"type": "echo", "data": message})
    except WebSocketDisconnect:
        return
