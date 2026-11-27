# Deployment

Local-first deployment of NEXUS AGENT OS via Docker Compose
(`docker-compose.yml` at the repo root, images under `infrastructure/docker/`).
This is the `docker compose up` path from `docs/SPEC.md` DoD §9.

> **Status:** the stack is validated statically by `tests/test_docker_stack.py`
> (Compose file, Dockerfiles, env contract). Running it end-to-end requires a
> Docker engine, which was unavailable in the slice's build environment — see
> the pull-request description for the recorded blocker.

## Quick start

```bash
cp .env.example .env        # then fill in secrets (see below)
docker compose up --build
```

Without a `.env`, the stack still starts: every `${VAR}` in
`docker-compose.yml` has a `:-default`. Fill `.env` before real use.

Verify:

| Check | Command / URL | Expected |
| --- | --- | --- |
| API health | `curl http://127.0.0.1:8000/health` | `{"status":"ok",...}` (200) |
| Frontend | <http://127.0.0.1:3000> | SPA shell loads |
| Bridge health | `curl http://127.0.0.1:8790/health` | `{"status":"ok",...}` (200) |

`docker compose ps` shows `healthy` next to **backend** before **frontend**
starts (`depends_on: condition: service_healthy`).

## Services and ports

| Service | Image built from | Host port (loopback only) | Container port | Notes |
| --- | --- | --- | --- | --- |
| `backend` | `infrastructure/docker/Dockerfile.backend` | `127.0.0.1:${NEXUS_BACKEND_PORT:-8000}` | 8000 | FastAPI + Alembic; runs migrations on start |
| `frontend` | `infrastructure/docker/Dockerfile.frontend` | `127.0.0.1:${NEXUS_FRONTEND_PORT:-3000}` | 3000 | nginx: serves SPA, proxies `/api/` and `/ws/` to `backend:8000` |
| `browser-bridge` | `infrastructure/docker/Dockerfile.bridge` | `127.0.0.1:${NEXUS_BRIDGE_PORT:-8790}` (via host network) | — | `network_mode: host`; binds host loopback only (SPEC §3.2) |

All published ports bind `127.0.0.1` only — nothing is exposed on LAN
interfaces. The bridge uses host networking because its code binds a fixed
loopback address; with `network_mode: host` that is the **host's** loopback,
so the userscript in your browser reaches `ws://127.0.0.1:8790` unchanged.
Host networking requires Docker Engine on Linux or Docker Desktop ≥ 4.34.

## Environment variables

`.env.example` documents every variable the stack reads; copy it to `.env`
and fill in secrets. Never commit `.env` (`.gitignore` and `.dockerignore`
both exclude it).

Secrets to set before real use (empty defaults keep the stack bootable but
degraded — the bridge local API answers `503` until `NEXUS_BRIDGE_API_TOKEN`
is set):

| Variable | Purpose | Generate with |
| --- | --- | --- |
| `NEXUS_JWT_SECRET` | Signs auth tokens | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `NEXUS_ENCRYPTION_KEY` | Fernet key for secrets at rest | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `NEXUS_BRIDGE_API_TOKEN` | Backend → bridge local API (≥ 32 chars) | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

Notes:

- **Database path is pinned in compose.** The backend container always uses
  `NEXUS_DATABASE_URL=sqlite+aiosqlite:////data/nexus.db` on the named volume
  `backend-data` (survives `docker compose down`; wipe with `down -v`). The
  `NEXUS_DATABASE_URL` in `.env` applies to host-side runs
  (`docs/DEVELOPMENT.md`). To use PostgreSQL with compose, override the
  variable in a `docker-compose.override.yml`.
- Host ports (`NEXUS_BACKEND_PORT`, `NEXUS_FRONTEND_PORT`, `NEXUS_BRIDGE_PORT`)
  only change the host side; container ports stay 8000/3000/8790. If you change
  `NEXUS_BRIDGE_PORT`, the bridge healthcheck follows it automatically.
- `NEXUS_BRIDGE_ALLOWED_ORIGINS` must list the origins the userscript runs
  from (e.g. `http://127.0.0.1:5173`) before a browser socket is accepted.

## Slice contracts

Each image builds from sources owned by a sibling slice. `docker compose build`
fails loudly until all of them land — nothing is faked:

| Image | Requires | Contract |
| --- | --- | --- |
| `backend` | backend slice (PR #2) | `pyproject.toml` + `backend/` at repo root; `GET /health` on port 8000; `alembic -c backend/alembic.ini upgrade head` |
| `frontend` | frontend slice (not yet opened) | root `package.json` + `package-lock.json` with a `build` script that emits `dist/` |
| `browser-bridge` | bridge slice (PR #4) | `integrations/browser-bridge/src/` with `app.py` entrypoint; `GET /health` on port 8790; deps `fastapi`, `uvicorn[standard]`, `pydantic` (no manifest yet — installed inline in the Dockerfile) |

Docker Compose is an alternative to `npm run desktop` (SPEC §10); both start
the same three services.

## Troubleshooting

- **`npm run build` / `Missing script: build`** — frontend slice not merged
  yet; build the rest with `docker compose up backend browser-bridge`.
- **Port already allocated** — change `NEXUS_BACKEND_PORT` / `NEXUS_FRONTEND_PORT`
  / `NEXUS_BRIDGE_PORT` in `.env`.
- **Frontend starts late** — by design: it waits for the backend healthcheck.
  Check `docker compose logs backend`.
- **Bridge unreachable from the browser** — confirm host networking is
  supported (Linux engine / Docker Desktop ≥ 4.34) and that
  `NEXUS_BRIDGE_ALLOWED_ORIGINS` contains your page's origin.
- **Reset local data** — `docker compose down -v` removes the `backend-data`
  volume; the next start re-runs migrations on an empty database.
- **Schema drift** — migrations run on every start; if startup fails in
  `alembic upgrade head`, check `docker compose logs backend`.

## Static validation

```bash
pytest tests/test_docker_stack.py   # no Docker required
```

validates `docker-compose.yml` against the official Compose specification
schema (vendored in `tests/data/`), the Dockerfile/healthcheck/port/env
contracts above, and that `.env.example` documents every `${VAR}` compose
references.
