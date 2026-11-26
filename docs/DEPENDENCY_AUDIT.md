# Dependency Audit

Latest versions were queried on 2026-11-26 with `npm view <pkg> version license` and `pip index versions <pkg>`.
They will be pinned exactly when each dependency is first installed. A dependency is added to the project only when a phase uses it.

## Python (backend, bridge, workers)

| Package | Latest | License* | Phase | Purpose / note |
|---|---|---|---|---|
| fastapi | 0.165.0 | MIT | 1 | API + bridge HTTP/WS |
| uvicorn | 0.54.0 | BSD-3 | 1 | ASGI server |
| websockets | 17.4 | BSD-3 | 1 | WS implementation |
| pydantic | 2.14.4 | MIT | 1 | Shared models |
| pyyaml | 6.0.4 | MIT | 1 | Adapter YAML |
| jsonschema | 4.26.0 | MIT | 1 | Adapter + event schema validation |
| httpx | 0.28.1 | BSD-3 | 1 | Clients (backend → bridge, Ollama) |
| sqlalchemy | 2.1.9 | MIT | 2 | ORM (async) |
| alembic | 1.20.1 | MIT | 2 | Migrations |
| aiosqlite | 0.22.1 | MIT | 2 | SQLite async driver |
| psycopg (v3) | 3.3.9 | LGPL-3.0 | 2 | PostgreSQL driver. Chosen over asyncpg because the LangGraph Postgres checkpointer requires psycopg 3 (TD-006). LGPL use as an unmodified library is fine |
| argon2-cffi | 25.1.0 | MIT | 2 | Password hashing |
| cryptography | 50.0.2 | Apache-2.0/BSD | 2 | Secret encryption at rest (Fernet/AES-GCM) |
| structlog | 26.1.0 | MIT/Apache-2.0 | 1 | JSON logs |
| langgraph | 1.2.24 | MIT | 4 | Workflow runtime |
| langgraph-checkpoint-sqlite | 3.1.3 | MIT | 4 | Pulls in aiosqlite and sqlite-vec |
| langgraph-checkpoint-postgres | 3.2.1 | MIT | 4 | psycopg 3 + psycopg-pool |
| sqlite-vec | 0.1.9 | MIT/Apache-2.0 | 6 | Vectors on SQLite |
| pgvector | 0.5.1 | MIT | 6 | Vectors on PostgreSQL |
| arq | 0.28.0 | MIT | optional | Redis job queue backend |
| redis | 8.2.0 | MIT | optional | Redis client |
| ruff | 0.17.6 | MIT | 1 | Lint/format |
| mypy | 2.4.1 | MIT | 1 | Types |
| pytest | 9.2.0 | MIT | 1 | Tests |
| pytest-asyncio | 1.5.0 | Apache-2.0 | 1 | Async tests |

Tooling: `uv` is installed and will manage Python environments and lock files.

## JavaScript / TypeScript (web, desktop, userscript, mock provider)

| Package | Latest | License | Phase | Note |
|---|---|---|---|---|
| react | 19.3.1 | MIT | 1 | |
| react-router | 8.5.3 | MIT | 1 | Major v8: verify API before use |
| vite | 8.4.0 | MIT | 1 | |
| typescript | 7.0.2 | Apache-2.0 | 1 | **Risk:** TS 7 is the native (Go) compiler. Check typescript-eslint support in Phase 1; if missing, pin the newest 5.x/6.x supported (TD-010) |
| tailwindcss | 4.3.5 | MIT | 1 | |
| @radix-ui/* (via shadcn/ui) | e.g. react-dialog 1.3.1 | MIT | 1 | shadcn components are generated into the repo (MIT) |
| lucide-react | 1.81.0 | ISC | 1 | Pinned (avoid CrewAI's `@latest` CDN mistake) |
| @tanstack/react-query | 5.108.4 | MIT | 1 | |
| zustand | 5.1.0 | MIT | 1 | |
| zod | 4.6.7 | MIT | 1 | |
| i18next / react-i18next | 27.2.9 / 18.0.3 | MIT | 1 | |
| @monaco-editor/react | 4.7.0 | MIT | 1 | Adapter YAML editor |
| dompurify | 3.5.0 | MPL-2.0 OR Apache-2.0 | 1 | Used under Apache-2.0 |
| esbuild | 0.28.2 | MIT | 1 | Userscript bundle |
| electron | 45.5.0 | MIT | 1 | Desktop shell |
| vitest | 5.1.2 | MIT | 1 | |
| @playwright/test | 1.65.1 | Apache-2.0 | 1 | Browsers must be installed (`npx playwright install chromium`) |
| @axe-core/playwright | 4.14.1 | MPL-2.0 | 1 | Dev-only, unmodified: acceptable |
| ajv | 8.20.0 | MIT | 1/4 | JSON Schema in the browser |
| eslint | 10.15.0 | MIT | 1 | Custom RTL / palette rules |
| streamdown | 2.8.1 | Apache-2.0 | 2 | Markdown streaming |
| @xterm/xterm | 6.0.0 | MIT | 5 | |
| react-diff-view | 3.3.3 | MIT | 5 | |
| framer-motion / motion | 14.14.0 | MIT | 3 | `motion` is the current package name |
| @xyflow/react | 13.0.3 | MIT | 3/4 | |
| @dagrejs/dagre | 3.1.4 | MIT | 3 | **Preferred** layout engine |
| elkjs | 0.12.2 | **EPL-2.0 OR GPL-3.0+** | — | Not adopted by default: weak copyleft. Use dagre; revisit only if needed (TD-011) |

\* Python licenses come from the projects' metadata as commonly published; each will be re-checked with `pip-licenses` once installed.
JS licenses come from `npm view`.

## Environment (2026-11-26)

Ubuntu 24.04 (kernel 7.0.0), Python 3.12.3, Node v22.23.3, npm 10.9.9 (no pnpm), uv installed, Docker 29.1.3 (usable without sudo),
Docker Compose 2.40.3, Google Chrome and Firefox installed, network available.
