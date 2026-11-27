"""Public liveness/readiness endpoints. No authentication is required by design."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from backend.app.core.config import Settings, get_settings
from backend.app.db.session import healthcheck
from backend.app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])

VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse, summary="Liveness and readiness")
async def health(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> HealthResponse:
    engine = getattr(request.app.state, "engine", None)
    database_ok = bool(engine is not None and await healthcheck(engine))
    stopped = getattr(request.app.state, "emergency_stop_engaged", False)
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        version=VERSION,
        database="ok" if database_ok else "unavailable",
        environment=settings.env,
        emergency_stop_engaged=bool(stopped),
    )
