# DEVELOPMENT LOG

## Session 2026-11-27 — Backend slice (`AATM-e7410b2b-c9c7-428b-b8ee-dd062c39afc3`)

### 1. Environment (verified, not assumed — SPEC §1.1)

| Item | Value |
|---|---|
| OS | Linux (x86-64), sandboxed workspace |
| Python | 3.11.2 (container runtime; project requires ≥3.11, CI uses 3.12) |
| Node | v22.22.3 (unused by this slice) |
| fastapi | 0.165.0 |
| sqlalchemy | 2.1.9 (async) |
| pydantic | 2.14.4 |
| alembic | 1.20.1 |
| Docker | **absent** |
| PostgreSQL | **absent as a system binary**; a real PostgreSQL 16 server was run from the `pgserver` wheel for verification |
| Network | PyPI reachable; `github.com` reachable |
| Package manager | venv + pip |

### 2. Work done

1. Read `docs/SPEC.md` end to end and derived the backend scope: §4 (architecture), §4.3 (events),
   §4.4/§4.5 (connection/runtime abstractions), §6 Phase 2 (auth, DB, agents, ReAct, tools, events),
   §6 Phase 3 (missions, DAG, PRs, reviews), §7 (event schema), §9 (gates), §11 (docs), §13 (policy,
   kill switch).
2. Built `backend/app/`: `core/` (config, logging+redaction, errors, security), `db/` (base, session
   with WAL pragmas, portable types), `models/` (34 tables), `schemas/`, `auth/` (RBAC + dependencies),
   `services/` (auth, agents, runs, events, tools, policy, connections, adapters, missions,
   approvals, audit, system), `api/routes/` (auth, agents, runs/events/approvals, tools,
   connections, missions/PRs, system/audit/kill-switch, health), `main.py`.
3. Wrote `docs/API.md` — the single shared contract, with example requests for every route group.
4. Wrote `backend/alembic/versions/0001_initial_schema.py` (one head revision, portable SQL).
5. Wrote `tests/test_backend_spec.py` (104 tests) and `tests/test_migrations.py`.
6. Added `scripts/check.sh`, `.github/workflows/backend.yml`, `pyproject.toml`, `.env.example`.

### 3. Decisions (also see `docs/TECHNICAL_DECISIONS.md`)

- **Portable DDL instead of native ENUM.** Enums are stored as `VARCHAR` through a `TypeDecorator`,
  and `JSON` becomes `JSONB` on PostgreSQL via `with_variant`. This keeps one revision valid on both
  backends and makes `alembic downgrade` work on PostgreSQL without dropping types.
- **The migration is plain ordered SQL**, generated from the live metadata and reviewed. Autogenerate
  produced `backend.app.db.base.UTCDateTime(...)` references that cannot execute, and
  `batch_alter_table` blocks that are SQLite-specific.
- **`get_session` reads `app.state.session_factory`.** Tests swap the engine without monkeypatching
  module globals.
- **Settings are pinned per app** via `app.dependency_overrides[get_settings]`, so `create_app(custom
  settings)` never mixes cached environment settings with the test configuration.
- **Explicit `match_all` for catch-all policy rules.** A rule with no matcher is rejected
  (`422 invalid_policy_rule`); the default policy clears its `ask` list before the catch-all, so
  force-push/payments always ask even in full auto.
- **Typed tool refusals stay typed.** A blocked host is a real `403 host_not_allowed` and a rejected
  expression a real `422 invalid_expression`; both are still audited and evented.

### 4. Tests run (exact commands and real results)

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest tests -q` | **106 passed, 1 skipped** (the PostgreSQL test skips unless `NEXUS_TEST_POSTGRES_URL` is set) |
| `pytest tests` with `NEXUS_TEST_POSTGRES_URL` set to a real PostgreSQL 16 database | **all passed** (suite ran twice against SQLite and once against PostgreSQL) |
| `alembic upgrade head` → `downgrade base` → `upgrade head` on empty SQLite | rc=0, 34 tables + `alembic_version` |
| Same on empty PostgreSQL 16 | rc=0, 34 tables, 63 foreign keys, `jsonb` + `timestamptz` columns |
| `.venv/bin/ruff check backend tests` | All checks passed |
| `.venv/bin/ruff format --check backend/app tests` | 56 files already formatted |
| `.venv/bin/mypy backend/app` | Success: no issues found in 52 source files |
| `./scripts/check.sh` | CHECK PASSED |

### 5. Bugs found and fixed during verification

1. Login lockout never persisted: the failed-login transaction was rolled back with the 401. Fixed by
   committing the counter/lock explicitly before raising.
2. `ConnectionOut.provider_slug` was required but was not an ORM attribute → 500 on connection
   create. Now resolved by the route, defaulting to `""`.
3. Default full-auto policy never allowed anything (an unmatcher'd catch-all was rejected), so every
   tool call asked. Fixed with the explicit `match_all` catch-all.
4. Approval ids were double-prefixed (`apr_apr_...`).
5. `TokenPair` was constructed with a duplicate `user` keyword after refresh.
6. `require` dependency had no return annotation under `mypy --strict` modules; typed.

### 6. Known issues / next step

- No WebSocket stream yet: clients replay via `GET /api/events?after_sequence=N`.
- No outbound HTTP in `http.get` (documented, returns `not_fetched`).
- Next step: frontend slice consumes `docs/API.md`; then the bridge/userscript slice adds the
  `/api/devices/pair` client flow and the WebSocket transport.
