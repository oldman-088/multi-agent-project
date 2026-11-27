"""Tests for the backend service's health endpoint."""

from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "backend"
    assert "version" in payload


def test_api_health_alias_returns_ok() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["service"] == "backend"


def test_root_is_discoverable() -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "backend"
    assert body["health"] == "/health"
