"""AATM API application."""
from fastapi import FastAPI

from app.api.routes import agents, events, runs
from app.services.store import Store


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(title="AATM API", version="1.0.0")
    app.state.store = store or Store()
    app.include_router(agents.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(events.router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
