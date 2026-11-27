# NEXUS AGENT OS

Local-first desktop and web application that runs a team of AI agents (a manager and N workers).
This repository currently contains the **backend slice**: a FastAPI modular monolith with the
database, authentication, REST contract, Tool Gateway, action policy and audit trail described in
[`docs/SPEC.md`](./docs/SPEC.md).

## Status

| Area | State |
|---|---|
| Backend REST API (`/api`) | Complete for this slice — see [`docs/API.md`](./docs/API.md) |
| Database models + Alembic (SQLite **and** PostgreSQL) | Complete |
| Auth, RBAC, audit, kill switch, action policy | Complete |
| Frontend, userscript, Local Browser Bridge, runtimes | Not started (later phases) |

Full, evidence-based status: [`docs/IMPLEMENTATION_STATUS.md`](./docs/IMPLEMENTATION_STATUS.md).

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
cp .env.example .env        # then set NEXUS_JWT_SECRET and NEXUS_ENCRYPTION_KEY

cd backend && NEXUS_DATABASE_URL="sqlite+aiosqlite:///./nexus.db" alembic upgrade head && cd ..

uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

- Interactive API reference: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/api/health>
- First run: `POST /api/auth/setup` (see [`docs/API.md`](./docs/API.md) §3.3)

## Quality gate

```bash
./scripts/check.sh     # ruff + mypy + pytest + Alembic round-trip
```

## Documentation

| Document | Purpose |
|---|---|
| [`docs/SPEC.md`](./docs/SPEC.md) | The authoritative specification (do not edit). |
| [`docs/API.md`](./docs/API.md) | The single shared REST contract: every route, request and response model, with examples. |
| [`docs/IMPLEMENTATION_STATUS.md`](./docs/IMPLEMENTATION_STATUS.md) | What is Complete / Partial / Not started, with test names. |
| [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md) | Setup, run and check the backend. |
| [`docs/DEVELOPMENT_LOG.md`](./docs/DEVELOPMENT_LOG.md) | Per-session log: environment, work, decisions, tests, issues. |
| [`docs/TECHNICAL_DECISIONS.md`](./docs/TECHNICAL_DECISIONS.md) | Context/options/decision/consequences records. |

## Security

- Passwords: argon2id. Secrets at rest: Fernet. Provider keys: `env:VAR_NAME` indirection.
- No secret, token or cookie is ever logged or returned; the audit writer redacts on write.
- Every route except the five public ones (`/api/health`, setup status/setup, login, refresh)
  requires a bearer token; RBAC is enforced in a service layer.
- The bridge host must be loopback (`Settings` refuses anything else).
