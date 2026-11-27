# DEVELOPMENT

## Requirements

- Python ≥ 3.11 (CI uses 3.12)
- SQLite (built in) for the default local-first setup, or PostgreSQL 16 for the multi-user setup
- No Docker required for this backend slice

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e "./apps/backend[test]"

cp .env.example .env
python -c "import secrets; print('NEXUS_JWT_SECRET=' + secrets.token_urlsafe(48))" >> .env
python -c "from cryptography.fernet import Fernet; print('NEXUS_ENCRYPTION_KEY=' + Fernet.generate_key().decode())" >> .env
```

Never commit `.env`. Secrets reach the app only through environment variables.

## Database

```bash
cd apps/backend
export NEXUS_DATABASE_URL="sqlite+aiosqlite:///./nexus.db"
alembic upgrade head

# PostgreSQL 16 (same revision, same commands)
export NEXUS_DATABASE_URL="postgresql+asyncpg://nexus:password@127.0.0.1:5432/nexus"
alembic upgrade head
```

The revision chain is portable: it creates 34 tables with `VARCHAR` enums, `JSONB` on PostgreSQL
and `TIMESTAMP WITH TIME ZONE` datetimes. `alembic downgrade base` removes everything again.
`0001_initial` is the schema, `0002_run_event_cursor` backfills `runs.last_sequence` so the event
cursor is atomic, and `0003_message_sequence_unique` de-duplicates and then indexes
`messages (conversation_id, sequence)`.

## Run the API

```bash
cd apps/backend       # so the `app` package is importable
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# http://127.0.0.1:8000/docs      interactive reference
# http://127.0.0.1:8000/openapi.json
# http://127.0.0.1:8000/api/health
```

First run: `GET /api/auth/setup-status` returns `needs_setup: true`; `POST /api/auth/setup` creates the
owner account and organization. See `docs/API.md` §3 for the exact payloads.

## Quality gate

```bash
./scripts/check.sh
```

Runs ruff (lint + format), mypy on `apps/backend/app`, pytest, and the Alembic round-trip. Set
`NEXUS_TEST_POSTGRES_URL` to a disposable database to include the PostgreSQL migration gate:

```bash
export NEXUS_TEST_POSTGRES_URL="postgresql+asyncpg://nexus:password@127.0.0.1:5432/nexus_ci"
./scripts/check.sh
```

Individual commands:

```bash
cd apps/backend
ruff check app tests
ruff format app tests
mypy app
pytest tests -q
pytest tests/test_backend_spec.py::test_agent_update_appends_immutable_version -q
```

## Layout

```
apps/backend/
  app/
    api/routes/    health, auth, agents, runs, tools, connections, missions, system
                   (agents.py, runs.py carry the routes; runs.py exposes the
                    /events and /approvals routers)
    auth/          rbac.py, dependencies.py
    core/          config, logging (JSON + redaction), errors, security
    db/            base (naming, mixins, UTCDateTime), session (WAL), types
    models/        identity, connections, agents, runs, collaboration, enums
    schemas/       common, auth, agents, runs, connections, workforce
    services/      auth, agent, run, event, tool, policy, connection, adapter,
                   mission, approval, audit, system
  alembic/         env.py + versions/0001_initial_schema.py, 0002_run_event_cursor.py,
                   0003_message_sequence_unique.py
  tests/           conftest.py, test_backend_spec.py, test_agents_routes.py,
                   test_runs_routes.py, test_events_routes.py, test_migrations.py
docs/              SPEC.md, API.md, IMPLEMENTATION_STATUS.md, DEVELOPMENT_LOG.md, ...
```

## Conventions

- Every mutating route: `auth.require("<permission>")`, an audit row, and (where it changes run
  state) an event — in the same transaction.
- Errors are raised as `AppError` subclasses so the JSON envelope is uniform.
- Never log request/response content; log ids, counts and durations only.
- New model → new Alembic revision written with the same portable-SQL discipline (see
  `docs/TECHNICAL_DECISIONS.md` TD-001).
- Anything that allocates a counter (`events.sequence`, `messages.sequence`) must do it in one
  atomic statement, never read-then-write, and the insert must retry under a SAVEPOINT. Two
  concurrent requests may not share a number.
- A decision that must happen once (an approval, a run transition) puts the expected current state
  in the `WHERE` clause of its `UPDATE` and treats zero rows affected as a 409.
