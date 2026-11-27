"""FastAPI application factory (SPEC §4.1 modular monolith, §10 layout).

Routers are mounted under ``/api`` so the frontend can use relative ``/api/...``
URLs and never hard-code a host (AGENTS.md frontend rules).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.app.api.routes import (
    agents,
    auth,
    connections,
    health,
    missions,
    runs,
    system,
    tools,
)
from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import register_error_handlers
from backend.app.core.logging import configure_logging, get_logger
from backend.app.db.session import create_engine, create_session_factory

logger = get_logger(__name__)

API_PREFIX = "/api"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests call this with their own settings."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("startup", extra={"extra_fields": settings.redacted_dump()})
        yield
        await engine.dispose()

    app = FastAPI(
        title="NEXUS AGENT OS — Backend API",
        version="0.1.0",
        description=(
            "Modular-monolith backend implementing the NEXUS AGENT OS specification: "
            "authentication and RBAC, agent versioning, runs and an authoritative event "
            "log, the Tool Gateway with an action policy, connections (browser session, "
            "local, API), missions with a validated task DAG, and the audit trail."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.emergency_stop_engaged = False

    # Pin dependency-injected settings to this app's instance so a factory call
    # with custom settings (tests, CLI) never falls back to the cached env copy.
    app.dependency_overrides[get_settings] = lambda: settings

    # Request id for correlation, echoed back and attached to audit rows.
    class RequestIdMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
            request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
            response = await call_next(request)
            response.headers["x-request-id"] = request_id
            return response

    app.add_middleware(RequestIdMiddleware)

    # The frontend is served from the same origin in production; in development
    # Vite proxies /api. Explicit origins come from configuration only.
    allowed_origins = list(settings.bridge_allowed_origins) or [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id", "X-Organization-Id"],
        expose_headers=["X-Request-Id"],
    )

    register_error_handlers(app)

    # ---------------------------------------------------------------- routes
    app.include_router(health.router)
    app.include_router(health.router, prefix=API_PREFIX, include_in_schema=False)

    api_routers = (
        auth.router,
        auth.members_router,
        agents.router,
        agents.conversations_router,
        runs.router,
        runs.events_router,
        runs.approvals_router,
        runs.system_router,
        tools.router,
        connections.router,
        connections.providers_router,
        connections.credentials_router,
        connections.devices_router,
        connections.tabs_router,
        connections.adapters_router,
        missions.router,
        missions.pr_router,
        system.router,
        system.audit_router,
        system.kill_switch_router,
    )
    for router in api_routers:
        app.include_router(router, prefix=API_PREFIX)

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "name": "NEXUS AGENT OS backend",
                "version": "0.1.0",
                "docs": "/docs",
                "api": API_PREFIX,
            }
        )

    return app


app = create_app()
