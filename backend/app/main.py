"""NEXUS AGENT OS backend — FastAPI application factory (docs/SPEC.md §4).

``create_app(settings)`` builds the modular-monolith app: core platform routes
(auth/RBAC, runs + events, Tool Gateway + approvals, emergency stop). The
module-level ``app`` reads ``NEXUS_*`` environment variables (CI sets
``NEXUS_DATABASE_URL``, ``NEXUS_JWT_SECRET`` and ``NEXUS_ENCRYPTION_KEY``).

On startup the lifespan brings the database to Alembic ``head`` (idempotent).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.auth import router as auth_router
from backend.app.api.routes.runs import router as runs_router
from backend.app.api.routes.system import router as system_router
from backend.app.api.routes.tools import router as tools_router
from backend.app.api.routes.users import router as users_router
from backend.app.core.config import Settings
from backend.app.core.db import make_engine, make_sessionmaker, run_migrations_async

logger = logging.getLogger("nexus.app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logging.basicConfig(level=logging.INFO)
    if settings.ephemeral_jwt_secret:
        logger.warning(
            "NEXUS_JWT_SECRET is not configured; using an EPHEMERAL in-process secret "
            "(tokens will not survive a restart). Configure it for anything persistent."
        )
    await run_migrations_async(settings.database_url)
    yield
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings if settings is not None else Settings()
    app = FastAPI(
        title=resolved.app_name,
        version=resolved.version,
        lifespan=lifespan,
    )

    if resolved.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.state.settings = resolved
    app.state.engine = make_engine(resolved.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)

    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(runs_router)
    app.include_router(tools_router)
    app.include_router(system_router)

    return app


app = create_app()


__all__ = ["app", "create_app"]
