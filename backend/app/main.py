"""Backend application entrypoint.

This is the minimal, working vertical slice of the NEXUS AGENT OS backend: a
FastAPI service that exposes a health endpoint. The Docker deployment and the
local deployment both run this exact module.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import FastAPI

APP_VERSION = os.getenv("APP_VERSION", "0.1.0")

app = FastAPI(
    title="NEXUS AGENT OS Backend",
    version=APP_VERSION,
    description="FastAPI backend for the NEXUS AGENT OS / AATM platform.",
)


def _health_payload(service: str) -> dict[str, str]:
    """Return the normalized health payload for a service."""
    return {
        "status": "ok",
        "service": service,
        "version": APP_VERSION,
        "time": datetime.now(UTC).isoformat(),
    }


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness/readiness probe for the backend (used by Docker healthchecks)."""
    return _health_payload("backend")


@app.get("/api/health", tags=["ops"])
async def api_health() -> dict[str, str]:
    """API-namespaced alias, proxied by the frontend through ``/api/...``."""
    return _health_payload("backend")


@app.get("/", tags=["ops"])
async def root() -> dict[str, str]:
    """Small discovery payload so the service root is not an empty 404."""
    return {
        "service": "backend",
        "version": APP_VERSION,
        "docs": "/docs",
        "health": "/health",
    }
