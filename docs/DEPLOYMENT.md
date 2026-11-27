# Deployment — Local Docker Stack

This document covers running the NEXUS AGENT OS stack locally with Docker
Compose: the **backend**, the **frontend**, and the **Local Browser Bridge**.

## Services

| Service | Image build | Listens on | Purpose |
|---|---|---|---|
| `backend` | `infrastructure/docker/Dockerfile.backend` | `:8000` | FastAPI application. Health endpoint at `/health`. |
| `frontend` | `infrastructure/docker/Dockerfile.frontend` | `:8080` | nginx serving the static app and reverse-proxying `/api` and `/ws`. |
| `bridge` | `infrastructure/docker/Dockerfile.bridge` | `:8765` (internal only) | Local Browser Bridge WebSocket transport. |

The frontend and the bridge reach the backend over an internal Docker network.
The backend's `/health` endpoint is published on the host so it can be probed.

## Prerequisites

- Docker Engine with the Compose plugin (`docker compose`).
- A `.env` file (see `.env.example`).

## Run the stack

```bash
cp .env.example .env          # then edit values as needed
docker compose up --build     # build and start in the foreground
# or, detached:
docker compose up -d
```

## Verify

Backend health:

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"backend","version":"0.1.0","time":"..."}
```

Frontend (proxies `/api/health` to the backend):

```bash
curl http://localhost:8080/api/health
# {"status":"ok","service":"backend","version":"0.1.0","time":"..."}
```

Bridge health (only reachable from other containers, by design):

```bash
docker compose exec bridge curl -s http://127.0.0.1:8765/health
```

Stop the stack:

```bash
docker compose down
```

## Environment variables

All variables are documented in `.env.example` with **placeholder values only**.
Never commit real secrets.

| Variable | Default | Meaning |
|---|---|---|
| `APP_VERSION` | `0.1.0` | Version reported by every service health endpoint. |
| `BACKEND_HOST` / `BACKEND_PORT` | `0.0.0.0` / `8000` | Backend bind address and port. |
| `BRIDGE_HOST` | `127.0.0.1` | Bridge bind address. |
| `BRIDGE_PORT` | `8765` | Bridge WebSocket port. |
| `BRIDGE_ALLOWED_ORIGINS` | local dev origins | Comma-separated origins allowed to open the WebSocket. |
| `BRIDGE_PAIR_TOKEN` | `change-me` | Paired credential required on every WebSocket handshake. |
| `FRONTEND_PORT` | `8080` | Host port for the frontend. |
| `DATABASE_URL` | SQLite | Storage URL (SQLite by default for the local setup). |

## Bridge networking note

The bridge's secure default is to bind to the loopback interface
(`BRIDGE_HOST=127.0.0.1`) and to require an `Origin` allow-list plus a paired
credential on every WebSocket handshake. Inside the Docker stack the compose
file sets `BRIDGE_HOST=0.0.0.0` so the backend can reach the bridge over the
**internal** network, and it does **not** publish the bridge port to the host.
The bridge is therefore never exposed to the host machine or the network.

## Running without Docker

Each service is a standard Python/FastAPI app and can run directly:

```bash
# backend
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --port 8000

# bridge
pip install -r integrations/browser-bridge/requirements.txt
BRIDGE_PAIR_TOKEN=change-me \
  uvicorn bridge.main:app --app-dir integrations/browser-bridge --port 8765
```

## Verification status

The deployment files are covered by automated tests in `tests/`
(`test_backend_health.py`, `test_bridge.py`, `test_docker_config.py`).

**Docker was not available in the environment where this was written**, so the
`docker compose up` flow was **not executed**. The service code was instead run
directly with uvicorn and its health endpoints and WebSocket handshake were
verified, and the compose/Dockerfile/env configuration was validated by the
tests above. No Docker build or run was claimed.
