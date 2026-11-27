"""NEXUS AGENT OS — backend package.

The backend is a FastAPI modular monolith. This module holds the application
entrypoint used by the container image (`infrastructure/docker/Dockerfile.backend`)
and by local development (`uvicorn app.main:app`).
"""
