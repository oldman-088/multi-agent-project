# Technical Decisions

Format: context → options → decision → consequences. Decisions fixed by SPEC §4 are not repeated here unless they need detail.

## TD-001 Package managers
- **Context:** pnpm is not installed; npm 10 and uv are installed.
- **Decision:** npm workspaces for JS/TS; uv for Python (one `pyproject.toml` per Python app, with a uv workspace at the root).
- **Consequences:** no extra global tool is needed. Lockfiles: `package-lock.json` and `uv.lock`.

## TD-002 Bridge pairing and credentials (hardening AATM)
- **Context:** AATM embeds a long-lived per-profile token inside the generated userscript (`backend/app/browser/arena_connector.py`, `build_userscript`).
  Anyone who receives the script file gets the credential.
- **Options:** (a) keep the embedded token; (b) pairing code → device credential.
- **Decision:** (b). The userscript ships with **no secret**. The bridge shows a 6–8 character one-time code (5 min TTL, single use, attempt-limited).
  The userscript exchanges it for a random device credential, which is stored hashed (SHA-256) on the bridge and kept in Tampermonkey storage (`GM_setValue`) on the page side.
  Each WebSocket session gets a short-lived session token (e.g. 10 min) that is renewed over heartbeat. Revocation deletes the hash and closes the socket immediately.
- **Consequences:** the userscript needs `@grant GM_setValue/GM_getValue` (documented in PERMISSIONS.md). This is a larger grant than AATM's `@grant none`, justified so that no secret is stored in page-visible localStorage.

## TD-003 Close codes
- **Decision:** a distinct code per reason (extends AATM's 4400/4401/4404/4409/4410):
  4400 bad hello/schema, 4404 not registered yet, 4401 bad credential, 4403 origin refused, 4426 script too old, 4410 revoked, 4409 replaced by a newer tab.
  The final list goes in `docs/PROTOCOL.md` in Phase 1.

## TD-004 Adapters as data
- **Decision:** `integrations/userscript/adapters/<provider>.yaml`, validated by a JSON Schema in `packages/contracts/adapter.schema.json`
  (with ajv in the userscript and jsonschema in the bridge). The bridge serves the active adapter in `config`, as AATM already does with `dom`/`stop_selectors`.
  Only `mock` and `generic` are enabled. Real providers are scaffolded disabled with `not_verified` capabilities.

## TD-005 Completion detection
- **Decision:** reuse AATM's proven rule as a configurable adapter field: generating indicator absent **and** text stable for `stable_ms`
  (default 1000), with a hard `timeout_ms`. Agent mode uses an idle double-check (`idle_ms`, default 5000) and a tool-limit settle period, as in AATM `computeState`.

## TD-006 LangGraph checkpointer and the database driver
- **Context:** the LangGraph checkpointers manage their own tables (`checkpoints`, `writes` on SQLite; `checkpoint_*` on Postgres) through
  aiosqlite / **psycopg 3**, not SQLAlchemy.
- **Decision:** use the same database file or database for both. On PostgreSQL, SQLAlchemy uses the `postgresql+psycopg` (async) dialect, so only one driver is needed (not asyncpg).
  Alembic's `include_object` excludes the LangGraph tables. Their schema is created by the checkpointer's `setup()`, which is called at worker startup.
- **Consequences:** "no second hidden state store" holds: everything lives in one database. Nodes that call `interrupt()` must be idempotent before the interrupt, because they re-run on resume.

## TD-007 Approval policy model
- **Decision:** follow the OpenHands `ConfirmationPolicyBase` shape (`always | never | risky(threshold)`). Risk comes from the **tool's declared metadata**
  in the Tool Registry, not from the model's self-report. A rejection becomes an `approval.rejected` event and an observation for the runtime.

## TD-008 Workforce recovery
- **Decision (Phase 3):** use explicit strategies like CAMEL's `RecoveryStrategy` (retry, replan, reassign), applied deterministically
  (retry up to N, then replan once, then escalate to the owner), with a pending-task cap similar to CAMEL's `MAX_PENDING_TASKS_LIMIT`.
  Plan validation reproduces the AATM semantics (unknown, self or cyclic dependencies; shared-contract warning; ambiguity question) in fresh code, because AATM has no license.

## TD-009 Live view technique (to be confirmed in Phase 1)
- **Options:** (a) a companion Chrome extension using `chrome.tabCapture`/`chrome.debugger`; (b) Playwright-controlled persistent profiles launched by Electron (CDP screencast + `Input.dispatch*`); (c) a "Focus this tab" fallback only.
- **Leaning:** (b) for Electron users, because it gives a screencast and input over CDP without a second extension, and the human signs in manually inside that profile. (c) is always offered.
  The final choice and limitations are recorded at the start of Phase 1, after a spike.

## TD-010 TypeScript version
- **Context:** npm's latest is TypeScript 7.0.2 (native compiler). Lint tooling may lag.
- **Decision:** checked in Phase 1. Use the newest version that typescript-eslint officially supports, and record the result here.

## TD-011 Graph layout
- **Decision:** `@dagrejs/dagre` (MIT). `elkjs` is EPL-2.0/GPL-3.0+, so it is not adopted unless a strong need appears.

## TD-012 AATM code reuse
- **Context:** `oldman-088/AATM` has no LICENSE file.
- **Decision:** no AATM code is copied (SPEC §3.4). NEXUS re-implements its ideas. If the owner adds a permissive license to AATM, record it and reconsider.
