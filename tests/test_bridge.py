"""Tests for the Local Browser Bridge.

Covers the health endpoint and the WebSocket handshake security model:
origin validation and the paired credential.
"""

from __future__ import annotations

import pytest
from bridge.main import app
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

ALLOWED_ORIGIN = "http://localhost:5173"
TOKEN = "test-pair-token"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("BRIDGE_PAIR_TOKEN", TOKEN)
    monkeypatch.setenv("BRIDGE_ALLOWED_ORIGINS", ALLOWED_ORIGIN)
    return TestClient(app)


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "bridge"


def test_websocket_accepts_valid_origin_and_token(client: TestClient) -> None:
    with client.websocket_connect(
        f"/ws?token={TOKEN}", headers={"origin": ALLOWED_ORIGIN}
    ) as ws:
        ws.send_text("ping")
        message = ws.receive_json()
        assert message == {"type": "echo", "data": "ping"}


def test_websocket_rejects_bad_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        "/ws?token=wrong", headers={"origin": ALLOWED_ORIGIN}
    ):
        pass


def test_websocket_rejects_untrusted_origin(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        f"/ws?token={TOKEN}", headers={"origin": "http://evil.example"}
    ):
        pass
