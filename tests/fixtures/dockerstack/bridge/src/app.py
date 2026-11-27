"""Minimal stand-in for the Local Browser Bridge used by the container smoke test.

It exposes the same surface as the real bridge: a `BridgeSettings` class that
reads its configuration from the environment and a `create_app` factory that
builds the FastAPI application with a public `GET /health` endpoint.  The real
bridge slice replaces this file as soon as it is merged.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

BRIDGE_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


@dataclass(frozen=True)
class BridgeSettings:
    """Configuration of the fixture bridge."""

    port: int = DEFAULT_PORT
    allowed_origins: frozenset[str] = frozenset()
    api_token: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "BridgeSettings":
        origins = {
            origin.strip()
            for origin in env.get("BRIDGE_ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        }
        return cls(
            port=int(env.get("BRIDGE_PORT", str(DEFAULT_PORT))),
            allowed_origins=frozenset(origins),
            api_token=env.get("BRIDGE_API_TOKEN", ""),
        )


def create_app(settings: BridgeSettings) -> FastAPI:
    """Build the fixture bridge application."""

    app = FastAPI(title="NEXUS Local Browser Bridge (fixture)")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "protocol_version": 1, "mode": "fixture"}

    return app


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    settings = BridgeSettings.from_env(os.environ)
    uvicorn.run(create_app(settings), host=BRIDGE_HOST, port=settings.port, log_level="warning")


if __name__ == "__main__":  # pragma: no cover
    main()
