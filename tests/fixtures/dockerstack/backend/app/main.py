"""Minimal FastAPI application used by the container smoke test.

It mirrors the public contract of the real backend: an application object at
`backend.app.main:app` and an unauthenticated `GET /health` endpoint.  The
container images are exercised against this fixture while the real backend
slice is not merged yet; as soon as the real slice is present the smoke test
runs against the real application instead.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="NEXUS backend fixture", version="0.0.0")


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness endpoint of the fixture."""

    return {"status": "ok", "version": "0.0.0", "mode": "fixture"}
