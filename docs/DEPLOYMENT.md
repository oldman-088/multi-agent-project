# Running the NEXUS stack locally

This document describes the container runtime environment of NEXUS AGENT OS:
the compose file, the three service images and the environment variables they
read.

| Artefact | Purpose |
|---|---|
| [`docker-compose.yml`](../docker-compose.yml) | The local stack: backend, frontend and browser bridge |
| [`infrastructure/docker/Dockerfile.backend`](../infrastructure/docker/Dockerfile.backend) | FastAPI backend, migrations applied on start |
| [`infrastructure/docker/Dockerfile.frontend`](../infrastructure/docker/Dockerfile.frontend) | Web application built with Node, served by nginx |
| [`infrastructure/docker/Dockerfile.bridge`](../infrastructure/docker/Dockerfile.bridge) | Local Browser Bridge |
| [`infrastructure/docker/frontend.nginx.conf`](../infrastructure/docker/frontend.nginx.conf) | Static hosting plus the `/api` and `/ws` proxy |
| [`infrastructure/docker/resolve_source.py`](../infrastructure/docker/resolve_source.py) | Finds the application sources at build time |
| [`infrastructure/docker/bridge_entrypoint.py`](../infrastructure/docker/bridge_entrypoint.py) | Starts the bridge inside a container |
| [`.env.example`](../.env.example) | Every environment variable, without real values |

## Prerequisites

* Docker Engine 24 or newer with the Compose V2 plugin (`docker compose`).
* At least 4 GB of free memory for the three images and their build caches.

Nothing else is needed on the host: the images contain Python 3.12, Node 22
and nginx.

## Quick start

```bash
cp .env.example .env       # optional: the defaults below already work
docker compose up --build
```

The stack is then reachable on the loopback interface of this machine only:

| Service | URL | Notes |
|---|---|---|
| Backend | <http://127.0.0.1:8000> | API under `/api`, health under `/health` |
| Frontend | <http://127.0.0.1:3000> | Web application, proxies `/api` and `/ws` to the backend |
| Browser bridge | <http://127.0.0.1:8790> | `ws://127.0.0.1:8790/ws/userscript` for the userscript |

Verify that the stack is up:

```bash
curl --fail http://127.0.0.1:8000/health    # {"status":"ok", ...}
curl --fail http://127.0.0.1:8790/health    # {"status":"ok", ...}
curl --fail http://127.0.0.1:3000/healthz   # ok
```

Stop the stack with `docker compose down`; add `--volumes` to delete the
SQLite database as well.

## What happens on `docker compose up`

1. The **backend** image is built. The image resolves the backend package
   (`backend/` or `apps/backend/`), installs its dependencies, creates an
   unprivileged user and starts with
   `alembic upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`.
   The migrations run before the first request is served, so the schema is
   always current.
2. The **frontend** image is built. The web application is compiled with
   `npm run build` and the resulting `dist/` directory is served by nginx.
   nginx proxies `/api/...` to the backend and upgrades `/ws` to a WebSocket
   connection, so the browser only ever talks to one origin and the frontend
   code can use relative URLs.
3. The **browser bridge** image is built. The bridge keeps its pairing store
   and its sessions in memory and exposes the local API and the userscript
   WebSocket.

The frontend and the bridge wait for the backend to report a healthy state
before they start.

## Environment variables

Every variable is documented in [`.env.example`](../.env.example) with a
default that works out of the box. Docker Compose reads `.env` from the
repository root automatically; the backend reads the same file when it runs on
the host.

The most important ones:

| Variable | Default | Meaning |
|---|---|---|
| `NEXUS_BACKEND_PORT` | `8000` | Host port of the backend |
| `NEXUS_FRONTEND_PORT` | `3000` | Host port of the frontend |
| `NEXUS_BRIDGE_PORT` | `8790` | Host port of the browser bridge |
| `NEXUS_ENV` | `development` | `development`, `test` or `production` |
| `NEXUS_LOG_LEVEL` | `INFO` | Log level of the backend |
| `NEXUS_DATABASE_URL` | `sqlite+aiosqlite:///./nexus.db` | Database used by host runs |
| `NEXUS_COMPOSE_DATABASE_URL` | `sqlite+aiosqlite:////data/nexus.db` | Database used inside the containers |
| `NEXUS_JWT_SECRET` | *(empty)* | Secret used to sign access tokens |
| `NEXUS_ENCRYPTION_KEY` | *(empty)* | Fernet key for credentials at rest |
| `NEXUS_BRIDGE_API_TOKEN` | *(empty)* | Bearer token for the bridge's local API |
| `NEXUS_BRIDGE_ALLOWED_ORIGINS` | *(empty)* | Origins allowed to open a bridge socket |

Secrets are never baked into an image and never committed: the templates stay
empty and the values are read from the environment at start time.

### Database

The containers store the SQLite database in the named volume `backend-data`,
which survives `docker compose down` and is only removed by
`docker compose down --volumes`.

To use PostgreSQL 16 instead, point the compose stack at it:

```bash
NEXUS_COMPOSE_DATABASE_URL=postgresql+asyncpg://nexus:CHANGE_ME@127.0.0.1:5432/nexus \
  docker compose up --build
```

The repository layer supports both databases; the migrations run on SQLite
and on PostgreSQL.

## Security notes

* **Every published port is bound to `127.0.0.1`.** The stack is reachable
  from the machine it runs on and from nowhere else.
* **The backend runs as an unprivileged user** (`nexus`, uid 10001) and writes
  only to the `backend-data` volume.
* **The frontend runs as `nginx`** (uid 101) in the unprivileged nginx image.
* **The bridge runs as an unprivileged user** (`nexus-bridge`, uid 10002) and
  keeps every piece of state in memory.
* **The bridge authenticates every client**: a one-time pairing code for the
  userscript, an origin allow-list on the WebSocket handshake and a bearer
  token for the local HTTP API. `NEXUS_BRIDGE_API_TOKEN` has to be at least 32
  characters; while it is empty the local API answers `503` and the pairing
  flow still works.
* **The userscript talks to the bridge through the loopback address**
  (`ws://127.0.0.1:8790/ws/userscript`), never through the container network.

### Why the bridge listens on `0.0.0.0` inside its container

`docs/SPEC.md` section 3.2 requires the bridge to bind `127.0.0.1` only, so
that it is never reachable from the network of the machine it runs on.

Inside a container that rule cannot be satisfied literally: a process that
listens on the loopback address of the container is unreachable from the host
and from the other services, and the published port would never answer. The
bridge therefore listens on all addresses *of its own network namespace*,
while the published port stays bound to `127.0.0.1` on the host. From the
outside the exposure is unchanged: nothing but this machine can reach the
bridge, and every client still has to pass the bridge's own checks.

Set `NEXUS_BRIDGE_BIND_HOST=127.0.0.1` to restore the strict bind. The
bridge then only answers requests that originate from inside the container,
which means the published port stops working.

## Design decisions

### The application directory is resolved at build time

The repository is assembled from independent slices, and the backend package
exists in two plausible places: `backend/` (repository root) and
`apps/backend/` (the layout of `docs/SPEC.md` section 10). A Dockerfile that
hard-codes one of them breaks as soon as the other slice is merged.

Every image therefore copies the repository once and asks
`infrastructure/docker/resolve_source.py` where the code is. The script writes
the resolved facts (package directory, import root, module path, Alembic
configuration, dependencies) to a small `KEY=VALUE` file that the image
sources before it starts. When a slice is missing the build fails with an
actionable message instead of producing an empty image.

The same applies to the web application (`apps/web/`, `web/` or a repository
root `package.json` with a `build` script) and to the bridge
(`integrations/browser-bridge/`).

### The bridge shares the network namespace of the backend

`browser-bridge` uses `network_mode: service:backend`, so both processes run
in the same network namespace:

* the backend reaches the bridge on `127.0.0.1`, which keeps the backend's
  own loopback-only validation of `NEXUS_BRIDGE_HOST` valid;
* the userscript reaches the same bridge through the published port
  `127.0.0.1:8790`;
* one port number covers both paths, so there is no second configuration for
  the same service.

The bridge port is published by the `backend` service, because that service
owns the shared namespace.

## Troubleshooting

**The build fails with "no backend application found".**
The backend slice is not in the repository yet. Merge it, or point the image
at the right directory by extending the candidate list in
`infrastructure/docker/resolve_source.py`.

**`alembic upgrade head` fails.**
The database URL is wrong or the directory is not writable. The containers
write to `/data`, which is the `backend-data` volume.

**The bridge health check stays unhealthy.**
The bridge needs at least 32 characters in `NEXUS_BRIDGE_API_TOKEN` for its
local API; the health endpoint itself does not need the token. Check
`docker compose logs browser-bridge`.

**A port is already in use.**
Change the host port in `.env`, for example `NEXUS_BACKEND_PORT=8010`. Only
the host side changes; the container keeps its internal port.

**The frontend shows the page but no data.**
The nginx proxy needs the backend service to be healthy; check
`docker compose ps` and `docker compose logs frontend`.

## Verifying the stack without Docker

The static validation of the compose file, of the images and of the
environment template runs without a Docker installation:

```bash
python -m pip install pytest pyyaml jsonschema
python -m pytest tests/test_docker_stack.py -q
```

The container smoke test itself needs Docker and runs in
`.github/workflows/docker-stack.yml`.
