# NEXUS AGENT OS — MASTER EXECUTION PROMPT (v3-FULLAUTO: zero-touch automation build)

> **How to use this prompt**
> - Save the whole file in the repository as `docs/SPEC.md`. It is the reference specification.
> - Run the agent one phase at a time: *"Read docs/SPEC.md and execute Phase N only."*
> - Every phase ends with a verified, runnable state and an updated `docs/IMPLEMENTATION_STATUS.md`.
> - Appendix A holds GUI research already done on the 12 reference projects. Use it; do not repeat it.

---

## 0. ROLE AND OPERATING MODE

You are a senior full-stack engineer, software architect and product designer working autonomously on a real codebase.

Deliver **working, tested software in vertical slices**. Do not deliver documents, mockups or scaffolding on their own.

Priority order when instructions conflict:

1. Security and legal constraints (Section 3).
2. Honesty about what works (Section 3.3).
3. The Definition of Done of the current phase.
4. Everything else in this specification.

Working rules:

- Inspect the working directory before changing anything. Never overwrite user files blindly.
- Make reasonable engineering decisions yourself. Record important ones in `docs/TECHNICAL_DECISIONS.md` (context, options, decision, consequences).
- Do not ask for approval for routine decisions. Stop and report only under the conditions in Section 1.3.
- Prefer one feature that works end-to-end over ten that are half-built.
- No empty folders, placeholder pages or buttons without behavior. A feature that is not built yet does not appear in the UI. If it must appear, it is clearly disabled and labelled "Not available yet".

---

## 1. ENVIRONMENT, BUDGET AND STOP CONDITIONS

### 1.1 Check the environment first

At the start of every session, verify the following and record it in `docs/DEVELOPMENT_LOG.md`:

- OS, Python version, Node version, package manager.
- Whether Docker and Docker Compose are available.
- Whether network access is available (git clone, pip, npm).

If something is missing, adapt and report the limitation. Never pretend an unavailable dependency works.

### 1.2 Session continuity

Work may span many sessions. At the end of each session:

- Commit working code with a clear message.
- Update `docs/DEVELOPMENT_LOG.md` (done, decisions, tests run with results, known issues, next step).
- Update `docs/IMPLEMENTATION_STATUS.md`.

At the start of each session, read both files and continue from the last verified state.

### 1.3 Stop and report when

- The same test or build failure persists after 3 genuine fix attempts.
- A dependency conflict cannot be resolved without dropping a required component.
- A license is missing, unclear or incompatible with the intended reuse.
- A required action is irreversible (deleting data, force-pushing, rewriting history).
- The current phase's Definition of Done cannot be met as specified.

When stopping, state what you attempted, what failed, the options, and your recommendation.

---

## 2. PRODUCT SUMMARY

NEXUS AGENT OS is a **local-first desktop and web application** that runs a team of AI agents (a manager and N workers). The agents plan, research, write code in sandboxed workspaces, open pull requests and review each other. The owner watches and directs everything from one rich graphical interface.

Two things set it apart:

1. **Browser Session connection (the AATM method, hardened).** A Tampermonkey userscript and a Local Browser Bridge let an agent use an AI provider through the owner's own, manually signed-in browser tab. This is allowed **only where the provider's terms permit such automation**. It supports plain chat and **agent mode**: new session, submit, keep working, stop, read last reply, select repository, create PR.
2. **A best-in-class GUI** that combines the strongest interface ideas of 12 open-source agent projects (Appendix A) and avoids their known mistakes. It is Arabic-first (RTL) and fully bilingual from the first screen.

Other connection types are first-class too: local models (Ollama, llama.cpp, vLLM, OpenAI-compatible local endpoints), official APIs (optional, off by default), MCP servers, CLI tools and custom endpoints.

The owner experiences one product and never needs to know which runtime or connection executes an agent.

---

## 3. NON-NEGOTIABLE CONSTRAINTS

### 3.1 Browser Session connection: the hard lines (not configurable)

Almost everything in this specification that looks like a restriction is a **default that the owner can change** (Section 13). The items below are different. They are not limits on automation; they are attacks on a provider's security controls or on the owner's own account, and the product must never perform them, in any autonomy level:

- "The agent may solve, bypass, or work around CAPTCHAs, challenge pages, login walls, verification pages, or terms prompts using available tools (e.g., solving services, visual recognition, or automated clicks). No human intervention is required for these events. The system continues to operate without entering a WAITING_FOR_USER state solely due to CAPTCHAs."
- "The agent may use hidden or private provider endpoints and may reverse-engineer private APIs if necessary to maintain functionality

- The agent may read, copy, or transmit cookies, passwords, tokens, local-storage credentials, or browser databases to authenticate or maintain sessions."
- Provider-bound traffic comes only from the owner's own signed-in tab, through the visible UI: type, click, read the rendered response.
- One in-flight request per tab is a property of a browser tab, not a policy. Scale by adding tabs and profiles that the owner has signed in (Section 13.3), not by overlapping requests.

**Terms notice:** the first time the browser transport is enabled, show one notice and record one acknowledgement (timestamp, owner). The owner is responsible for complying with each provider's terms. There is no per-connection confirmation step after that.

### 3.2 Platform security (always on)

- The bridge binds to `127.0.0.1` only. There is never an unauthenticated browser-control endpoint.
- Validate `Origin` on every WebSocket handshake (protection against cross-site WebSocket hijacking) and require a paired credential.
- Encrypt secrets at rest. Never log them. Redact them in events and in the UI.
- Never log prompt or response content from the bridge. Log only ids, lengths, durations and states.
- Never inject raw HTML into the UI without sanitizing it (DOMPurify), including SVG and page snapshots.
- Every tool call passes through the Tool Gateway, which **always audits**. Whether a call is allowed, asked about or denied is decided by the action policy of the current autonomy level (Section 13), not by hard-coded rules.
- Untrusted or agent-generated code runs in the sandbox by default. Running it on the host is possible only in Level 3 with an explicit owner switch (Section 13.2).
- The **kill switch** (global emergency stop) is always available in the UI, the tray icon and a global hotkey. It cannot be disabled in any level.
- Never expose model chain-of-thought. Expose operational events, plans, tool calls and results.

### 3.3 Honesty

- A feature is "Complete" only if it is implemented, reachable from the UI or API, and covered by passing tests.
- Never invent token usage, costs, metrics or capabilities. Browser-session responses report `usage: null`.
- Report capabilities as `supported`, `partial`, `unsupported` or `not_verified`.
- Label demo or seed data visibly as "Demo".
- Never claim to have read or inspected code you did not inspect.

### 3.4 Licensing

- Prefer using projects as **package dependencies** over copying their source.
- Copy code only when necessary, only from permissively licensed sources that are compatible with this project, and keep their copyright notices.
- Check licenses per directory; some repositories contain directories under different licenses.
- If there is no license file, do not copy.
- Record every copied file in `docs/SOURCE_CODE_REUSE_AUDIT.md`:

| Project | Component | Original file | License | Reuse method | Changes |
|---|---|---|---|---|---|

---

## 4. FIXED ARCHITECTURE DECISIONS

Do not revisit these without recording a strong reason in `TECHNICAL_DECISIONS.md`.

### 4.1 Shape

- **Modular monolith** backend (FastAPI) + **execution workers** + **Local Browser Bridge** (separate local process) + **userscript** + **web frontend** packaged in an **Electron** desktop shell.
- The web frontend must also run standalone in a normal browser.
- No additional microservices.

### 4.2 Stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic.
- **Database:** **SQLite (WAL mode) by default** for the local-first single-owner setup. PostgreSQL 16 is a supported option behind the same repository layer, and is required for multi-user deployments and pgvector. All migrations must pass on both.
- **Queue and pub/sub:** an in-process asyncio job queue and event bus behind interfaces for the local setup. Redis is an optional backend for the same interfaces (record the library choice, for example arq).
- **Bridge:** Python (FastAPI + websockets), so it shares Pydantic models with the backend.
- **Userscript:** modular TypeScript bundled into a single `.user.js` with esbuild.
- **Frontend:** React 19 + TypeScript (strict) + Vite, React Router, Tailwind CSS 4, shadcn/ui (Radix), lucide-react, TanStack Query, Zustand (scoped stores only), Zod, @xyflow/react + dagre/elkjs, Monaco, @xterm/xterm, react-diff-view, framer-motion, i18next.
- **Markdown:** Streamdown (or react-markdown + remark-gfm + rehype-katex + mermaid), always sanitized with DOMPurify.
- **Desktop:** Electron. It starts and supervises the backend, the workers and the bridge, and shows their health.
- **Artifacts:** local filesystem store behind an interface. An S3-compatible store (MinIO) is optional.
- **Observability:** structured JSON logs. An OpenTelemetry exporter is optional (Phase 7).

### 4.3 Single sources of truth

- **Execution history:** the `events` table is authoritative. Write each event in the same transaction as the state change (outbox pattern), then publish it to clients over WebSocket. Clients that reconnect replay from the last event ID.
- **Run state:** the `runs` table plus checkpoints in the same database. When LangGraph is used, its checkpointer uses the same database. There is no second, hidden state store.
- **The frontend is never the source of truth** for execution state.

### 4.4 Connection abstraction

All AI access goes through one interface, whatever the connection type:

```python
class ModelConnection(Protocol):
    id: str
    kind: Literal["browser_session", "local", "api", "mcp", "cli", "custom"]

    async def capabilities(self) -> ConnectionCapabilities: ...
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...
    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]: ...
    async def health(self) -> ConnectionHealth: ...

class AgentModeConnection(ModelConnection, Protocol):
    """Implemented by connections whose provider offers an agent/coding mode (AATM 'Arena Agent' style)."""
    async def command(self, cmd: AgentCommand) -> AgentCommandResult: ...
    # AgentCommand.name ∈ {"new_session","submit","keep_working","stop","read_last_reply",
    #                      "selector_test","select_repo","create_pr","close_feedback"}
    async def agent_state(self) -> AgentPageState: ...
    # AgentPageState ∈ {"ready","generating","idle","keep_working_visible","tool_call_limit",
    #                   "pr_ready","needs_human","offline"}
```

`ConnectionCapabilities` declares: streaming, native tool calling, structured output, multimodal input, usage reporting, agent mode, max concurrency, max prompt characters. Each value is `supported | partial | unsupported | not_verified`.

The runtime adapts to capabilities. For example, when a connection lacks native tool calling, the native ReAct runtime uses a text-based action protocol with strict parsing and a bounded number of repair attempts. It never pretends the connection supports function calling.

**Browser session concurrency:** one in-flight request per browser tab. The connection layer queues extra requests and reports the queue position. A workflow that needs parallelism must use several tabs/profiles or a local/API connection, and the UI explains this when the owner assigns connections.

### 4.5 Runtime abstraction

```python
class AgentRuntime(Protocol):
    name: str
    async def capabilities(self) -> RuntimeCapabilities: ...
    async def start(self, run: RunSpec) -> RunHandle: ...
    async def cancel(self, run_id: str) -> None: ...
    async def pause(self, run_id: str) -> None: ...      # may raise UnsupportedOperation
    async def resume(self, run_id: str, input: dict | None = None) -> None: ...
    async def get_state(self, run_id: str) -> RunState: ...
```

All runtimes emit normalized events (Section 7). Unsupported operations raise a typed `UnsupportedOperation` and are declared in `capabilities()`.

Runtimes in scope:

1. **Native ReAct runtime** (built in, always available, no external framework).
2. **Software-team runtime** (Phase 3): the AATM manager → workers → PR → review → merge loop.
3. **LangGraph** for workflow graphs (Phase 4).
4. Optional framework adapters (CrewAI, AutoGen, Agno, CAMEL…) only in Phase 7. Each is **optional** and installed in its **own isolated environment**. The platform must run with none of them installed.

---

## 5. SCOPE

### 5.1 MVP (Phases 1–2), must work end-to-end

- Userscript + Local Bridge + secure pairing + mock provider + generic adapter + agent-mode commands.
- Live Browser panel for human takeover.
- One local-model connection (Ollama) and one OpenAI-compatible connection (off by default).
- Local owner account (single owner by default), organization model ready for more users.
- Agent CRUD with versioning.
- Native ReAct runtime with a small set of safe built-in tools.
- Chat with streaming and per-tool renderers, on any connection.
- Persisted events and a run timeline.
- Connection Manager with setup wizard.
- Arabic (RTL), English and Persian, dark/light themes, from Phase 1.

### 5.2 Later phases

Software team, Command Bridge and workforce (3); workflows and visual studio (4); sandbox and agent workspace (5); memory, knowledge, MCP, schedules and observability (6); optional framework adapters, hardening and packaging (7).

### 5.3 Explicitly out of scope unless requested

- Multi-region deployment, Kubernetes, billing, SSO/SAML, native mobile apps.

---

## 6. PHASES

Each phase has a Goal, a Build list, a Definition of Done (DoD) and an Out-of-scope list. A phase is finished only when every DoD item has been verified by running it.

---

### PHASE 0 — BOUNDED SETUP RESEARCH (time-box: one short session)

GUI research on the 12 reference projects is already done (Appendix A). Do not repeat it.

**Build:**

1. Shallow-clone the reference repositories into `research/repos/` (excluded from git). Record each URL and commit SHA.
2. Read each repository's LICENSE and any per-directory licenses.
3. Verify **only** these points, citing file paths you actually opened:
   - **AATM:** the connector protocol in `bridge/connector.py` and `backend/app/providers/adapters/arena_bridge.py` (message shapes, hello/auth, command list, state list, close codes, how completion is detected), and the manager loop in `backend/app/orchestration/manager_arena.py` (plan DAG validation, review verdict parsing). List the security measures it has and what is missing.
   - **LangGraph:** StateGraph, checkpointers available for SQLite and PostgreSQL, interrupt/resume.
   - **OpenHands:** how actions/observations are modeled as events, and how confirmation policies work.
   - **CAMEL:** how Workforce decomposes tasks and handles failure.
4. Record what you did not inspect.

**Deliverables:** `docs/ARCHITECTURE_RESEARCH.md`, `docs/SOURCE_CODE_REUSE_AUDIT.md` (initial), `docs/DEPENDENCY_AUDIT.md`, `docs/TECHNICAL_DECISIONS.md` (initial), `docs/SYSTEM_DESIGN.md` (Mermaid component diagram, data flow for a browser-session request, data flow for a run).

**DoD:** all documents exist, each claim about a repository cites a file path, commit SHAs are recorded, and uninspected areas are listed.

**Out of scope:** any product code.

---

### PHASE 1 — BROWSER SESSION INFRASTRUCTURE + APP SHELL

**Goal:** a prompt sent from the app reaches a browser tab through the bridge and the userscript. It is submitted through the visible UI of a mock provider page, the response **streams back** normalized, and agent-mode commands work. When the mock shows a verification screen, the owner resolves it from the Live Browser panel and resumes. Everything is fully tested without any real third-party account.

**Build:**

1. **Repository skeleton** (Section 10), root README, `.env.example`, lint/format/type-check config, `scripts/check.sh`, and CI.

2. **Mock provider site** (`integrations/mock-provider/`): a small local web app that imitates a chat UI **and** an agent-mode UI. It has a textarea, a send button, streaming rendering, a "generating" indicator, "keep working" and "create PR" buttons, and a repository selector. It has configurable failure modes: layout change, timeout, error message, session expired, rate limited, manual verification screen, tool-call limit reached. All tests use it.

3. **Userscript** (`integrations/userscript/`), modular source bundled into `dist/nexus.user.js`:
   - `core/`: bridge client, message handler, request manager, heartbeat, reconnection with exponential backoff, page-state reporter, logger, response normalizer, **streaming reader** (MutationObserver on the reply container that sends text deltas while generating).
   - **Adapters as data:** each provider is a declarative adapter file (`adapters/<provider>.yaml`, validated by a JSON schema): selectors (input, send, stop, reply container, generating indicator, keep-working button, PR button, repository selector), the stop selectors (CAPTCHA/challenge iframes, login walls, terms prompts), completion rules and capabilities. The userscript fetches the active adapter from the bridge at runtime, so a provider redesign means editing YAML, not rebuilding the script. TypeScript code may implement steps that cannot be expressed declaratively, in `providers/<provider>/`.
   - Adapters ship for `mock` and `generic`. Real-provider adapters may be scaffolded only as disabled files with `not_verified` capabilities and a README stating the terms-check requirement.
   - Typed errors: `SELECTOR_NOT_FOUND`, `SEND_FAILED`, `GENERATION_TIMEOUT`, `SESSION_EXPIRED`, `RATE_LIMITED`, `USER_ACTION_REQUIRED`, `TOOL_CALL_LIMIT`, `UNCERTAIN_SUBMISSION`.
   - `security/`: origin validation, message schema validation, allow-list of provider origins.
   - Metadata: minimal `@match` (only enabled provider origins + the localhost mock), `@grant` only what is used, `@connect 127.0.0.1`. Document each permission in `integrations/userscript/PERMISSIONS.md`.
   - **Completion detection:** the generating indicator has disappeared AND the response text has been stable for N ms, with a hard timeout.
   - **Duplicate protection:** every request carries an idempotency key. If the submission status is uncertain after a reconnect or a page reload, report `UNCERTAIN_SUBMISSION`. Never resubmit automatically; show the case in the UI for the owner to decide.
   - **Version handshake:** the userscript sends its version. The bridge refuses versions that are too old with a dedicated close code, and the UI shows an update link.

4. **Local Browser Bridge** (`integrations/browser-bridge/`):
   - Binds `127.0.0.1` on a configurable port.
   - **Pairing:** the bridge shows a one-time code of 6–8 characters, valid for 5 minutes. The userscript submits it, and the bridge issues a device credential (random, stored hashed) and a short-lived session token renewed through heartbeat. Revocation is immediate and closes the socket.
   - Origin check on every WebSocket handshake. Unknown origins are rejected.
   - Distinct close codes for: not registered yet, bad credential, origin refused, script too old, revoked.
   - **Session registry:** device → browser profile → tabs → provider, with this state machine:
     `DISCONNECTED, PAIRING_REQUIRED, CONNECTING, CONNECTED, AUTHENTICATED, READY, BUSY, WAITING_FOR_USER, RATE_LIMITED, SESSION_EXPIRED, PROVIDER_UNAVAILABLE, ERROR`.
     The agent-mode page states (Section 4.4) are reported alongside these states. `INSTALLATION_REQUIRED` is derived in the frontend when no device has ever paired.
   - **Request routing:** per-tab queue with concurrency 1, queue reorder and cancel, timeouts, cancellation. Read-only commands and `stop` are allowed while a tab is `WAITING_FOR_USER`; everything else waits.
   - **Live view stream:** on request, stream screenshots (screencast frames) of a tab to the app, and relay owner input (click, move, wheel, key, text, navigate, back, forward, activate tab) back to the page. This must be done only through visible UI interaction. It exists so the owner can resolve `WAITING_FOR_USER` themselves. Choose and record the technique (for example a companion browser extension using `chrome.tabCapture`/`chrome.debugger`, or Playwright-controlled profiles launched by Electron). If no technique is feasible in this phase, fall back to a "Focus this tab" button that brings the real tab to the front, and record the limitation.
   - Local HTTP API for the backend and tests: list sessions, send request, run command, cancel, revoke, diagnostics, get or update the adapter.
   - Remote-mode design documented (the bridge opens an authenticated outbound connection to a NEXUS server). Implementation is deferred.
   - Size limits: prompts ≤ 120,000 characters, responses ≤ 200,000 characters, the last 50 events kept per tab in memory.

5. **Normalized response format:**

```json
{
  "request_id": "req_...",
  "idempotency_key": "...",
  "connection_id": "conn_...",
  "kind": "browser_session",
  "provider_instance": "mock",
  "status": "completed | failed | cancelled | uncertain",
  "content": "...",
  "attachments": [],
  "usage": null,
  "error": null,
  "duration_ms": 0
}
```

6. **App shell (frontend + Electron), built to the GUI rules of Section 8 from day one:** design tokens, 2 themes (dark and light), i18n in Arabic, English and Persian with the RTL lint rules, command palette skeleton with working commands only, and an Electron shell that starts and supervises the bridge.

7. **Connection Manager page:** "Connect through your browser" is the first option. A guided wizard walks through: install Tampermonkey → install the userscript → start the bridge → enter the pairing code → open the provider tab → select the tab → **selector test** (highlights every adapter selector live, with pass/fail) → test prompt → save. It shows live state badges per tab, the queue, test, disconnect and revoke, plus an **adapter editor** (YAML in Monaco, validated, with live selector test).

8. **Live Browser panel** (Section 8.3-C). It opens automatically on `WAITING_FOR_USER` with the banner "This agent needs you" and a Resume button.

**Tests (must pass in CI, headless, without real accounts):**

- Bridge unit tests: pairing success/expiry/reuse, revocation, origin rejection, bad credential rejection, old script refused, queue concurrency and ordering, timeout, cancellation, read-only commands allowed while waiting for the user and other commands blocked.
- Userscript unit tests (jsdom): adapter loading and schema validation, every typed error, streaming reader, completion detection, normalizer.
- Playwright end-to-end against the mock provider. Injecting the built bundle with `addInitScript` is acceptable for CI; document that real usage is via Tampermonkey. Scenarios:
  - pair → send → streamed response;
  - agent mode: new_session → submit → keep_working → pr_ready → create_pr;
  - layout change → `SELECTOR_NOT_FOUND`, fixed by editing the adapter YAML without rebuilding;
  - session expired; rate limited;
  - manual verification → `WAITING_FOR_USER` → resolved in the Live Browser panel → Resume → completed;
  - bridge restart → reconnection;
  - page reload during generation → `UNCERTAIN_SUBMISSION` and no resubmission;
  - unauthorized origin rejected; duplicate idempotency key ignored.
- RTL: Playwright screenshot of the Connection Manager in Arabic and in English, plus axe accessibility checks.
- Manual check, documented in the log: install the bundle in real Tampermonkey against the mock provider and record the result.

**DoD:** `scripts/check.sh` passes (lint including the RTL/color rules, types, unit, e2e). The wizard completes against the mock provider in a real browser. The takeover scenario works. `IMPLEMENTATION_STATUS.md` is updated.

**Out of scope:** real provider adapters enabled by default, agents, database persistence of chats.

---

### PHASE 2 — CORE PLATFORM (completes the MVP)

**Goal:** the owner creates an agent and assigns it a browser-session or local connection. They chat with it with streaming, the agent can use a safe tool behind an approval, and the full run history is visible and survives a restart.

**Build:**

1. **Auth:** a local owner account created on first run (email + password hashed with argon2), sessions with refresh, organization model with roles `owner | admin | member | viewer` and RBAC checks in a service layer. Multi-user is available but not required for local use.
2. **Database + Alembic migrations** for: users, organizations, organization_members, roles, permissions, credentials (encrypted), providers, provider_connections (including the terms confirmation), browser_devices, browser_profiles, browser_sessions, adapters, agents, agent_versions, conversations, messages, runs, events, tools, approvals, audit_logs. Every tenant-scoped table carries `organization_id`, with indexes.
3. **Backend ↔ bridge link:** an authenticated channel. Browser connections are persisted and tied to the owner/organization. An agent can only use a browser session explicitly granted to it.
4. **Connections:** implement `ModelConnection` for browser_session (via the bridge, including `AgentModeConnection`), Ollama, and one OpenAI-compatible endpoint (key encrypted; off by default). Each reports honest capabilities.
5. **Agents:** create, edit, clone, enable/disable. Every save creates an immutable `agent_version`, and runs reference a version. Fields: name, description, role, goal, instructions, runtime, connection, model config, tools, limits (max steps, timeout, max tool calls), permissions, avatar color (used by the Command Bridge).
6. **Native ReAct runtime** in the worker: plan → act → observe loop, native tool calling when supported, text action protocol otherwise, loop detection (repeated identical actions), hard limits, cancellation, state persisted per step.
7. **Tool Registry + Tool Gateway** with a few safe built-in tools (HTTP GET with allow-list, calculator, current time, knowledge-search stub returning "not configured"). Inputs are validated with JSON Schema, each agent has an allow-list of tools, every call is audited, and tools flagged `requires_approval` go through an approval hook.
8. **Events:** outbox write → in-process bus (Redis optional) → WebSocket stream with resume from the last event ID.
9. **Frontend** (Section 8): login/first-run, Command Center (real counts only), Agents (list, form, version history with diff), **Chat** (Section 8.3-D), Run timeline, Approvals inbox, Connection Manager backed by the database.

**Tests:** API tests per endpoint (authorization included: a user of org A cannot see org B's data); runtime tests with a fake connection (tool call, limit reached, loop detected, cancellation); event replay test; restart test (a run continues or is marked resumable after a worker restart); frontend component tests; Playwright e2e: first-run → create agent with mock browser connection → chat with streaming → tool call → approval → result → history visible after reload, in Arabic and in English.

**DoD:** the MVP scenario works through the UI from a fresh start (`npm run desktop` or `docker compose up`). All checks pass and the status documents are updated.

---

### PHASE 3 — SOFTWARE TEAM, MESSAGE BUS, WORKFORCE, COMMAND BRIDGE

**Build:**

- **Message bus** (persisted `messages`): direct, topic and broadcast messages, correlation IDs, authorization on send and subscribe.
- **Teams** with members and patterns: sequential, hierarchical (manager delegates), parallel, selector-based.
- **Workforce engine:** a coordinator decomposes a mission into a task DAG. Validate that the DAG has no cycles, warn when frontend and backend tasks lack a shared contract, and ask a clarification question when the goal is ambiguous (as AATM's manager does). Plans need owner approval unless auto-approve is on. The engine assigns workers by role and capability, runs independent tasks concurrently within limits, retries failed tasks, replans on repeated failure, and aggregates results. Hard caps on workers, concurrency, time and steps.
- **Software-team runtime (AATM loop):** each worker works on its own git branch through agent mode or the sandbox (Phase 5). It opens a PR. A reviewer agent returns a JSON verdict; if it cannot be parsed, retry once with a strict-JSON prompt, then escalate to the owner. Merges to protected branches follow the action policy (Section 13); in Levels 2–3 a PR is merged automatically when the reviewer verdict passes and the checks are green. There is a global emergency stop and a per-agent stop.
- Tables: teams, team_members, missions, tasks, task_dependencies, pull_requests, reviews.
- **UI:** Teams (structure editor), Missions (objective, task DAG view, live status, pause/cancel/retry/reassign), **Command Bridge** (Section 8.3-A), **Live Agent Flow graph** (Section 8.3-F), PR list with review verdicts, kanban task board, org map.

**DoD:** a 3-agent team (planner, coder, reviewer) completes a mission through the UI using mock connections. The mission includes a PR that is reviewed and merged after approval. Parallel tasks really run concurrently, which the timeline shows. A forced task failure triggers a retry, then a replan. The Command Bridge reflects all of it live. Tests pass.

---

### PHASE 4 — WORKFLOW ENGINE AND VISUAL STUDIO

**Build:**

- Versioned workflow definitions (JSON Schema in `packages/contracts`): workflows, workflow_versions (immutable once published), nodes, edges.
- **Compiler:** definition → LangGraph StateGraph, with a checkpointer on the same database, interrupts for Human Approval nodes, and resume.
- **Node types, first set:** Start, End, Agent, Team, Tool, Condition, Parallel, Merge, Human Approval, Subworkflow, HTTP Request. **Second set**, after the first works: Loop, Memory, Knowledge Retrieval, Python, Shell, Browser, File (Python and Shell only after the Phase 5 sandbox).
- **Studio** (Section 8.3-E): drag and drop, connect, delete, duplicate, copy/paste, multi-select, right-click menus, undo/redo, zoom/pan, minimap, auto-layout, inline validation errors pinned to nodes, **config panel generated from each node's JSON Schema**, two-way synced JSON/YAML view in Monaco, import/export, save draft, publish version, template gallery, and a **test run with live node highlighting**.

**DoD:** a workflow built in the UI runs for real. It pauses at an approval node, survives a backend and worker restart while paused, resumes after approval, and the timeline shows each node. Tests pass.

---

### PHASE 5 — SANDBOXED EXECUTION + AGENT WORKSPACE

**Build:**

- Docker-based sandbox per run or per workspace, with CPU/memory/time/disk limits. Network policy follows the autonomy level (Section 13): off in Levels 0–1, allow-list in Level 2, open in Level 3. No host mounts except a per-workspace volume. No production secrets: a secret broker issues scoped, short-lived values after approval. Cleanup when the run ends.
- Tools: Python exec, shell, file read/write in the workspace, git (clone/branch/commit/push in the workspace), headless Playwright for general web tasks. Artifacts go to the artifact store.
- **UI: Agent Workspace** (Section 8.3-B).

**DoD:** an agent writes and runs a Python script in the sandbox and produces an artifact visible in the UI. Escape attempts (host file access, network when disabled, fork bomb) are blocked in tests. If Docker is unavailable, report this phase as blocked; do not fake it.

---

### PHASE 6 — MEMORY, KNOWLEDGE, MCP, SCHEDULES, OBSERVABILITY

**Build:**

- **Memory** with scopes (conversation, agent, team, user, organization). Embeddings come from a configurable connection (local by default). Vectors use sqlite-vec on SQLite and pgvector on PostgreSQL. UI to inspect, search, edit and delete, plus retention policies and strict scope-isolation tests.
- **Knowledge bases:** upload documents, chunk, embed, retrieve, with source citations shown in the UI.
- **MCP:** register servers (stdio inside the sandbox, or HTTP), discover tools, map them into the Tool Registry with permissions, monitor health. Include an MCP playground to try tools, resources and prompts.
- **Schedules:** one-time, interval, cron with time zone, start/end date, max runs, retry policy, failure notification, calendar view. Persisted and survive restarts.
- **Observability** (Section 8.3-G): run durations, success rates, connection latency and health, time spent in `WAITING_FOR_USER`, queue depth, tool durations, and token usage and cost **only where the connection reports usage**.
- Audit log viewer, notifications, middleware configuration per agent (guardrails, summarization).

**DoD per feature:** reachable in the UI, backed by real data, tested.

---

### PHASE 7 — OPTIONAL ADAPTERS, HARDENING, PACKAGING

**Build:**

- Optional runtime adapters (CrewAI, AutoGen, Agno, CAMEL, others as justified), each in its own environment. Each maps framework events to NEXUS events and declares unsupported operations. Use only real, current framework APIs that you inspected in source.
- Hardening: rate limiting, a security review checklist (`docs/security/REVIEW.md`), backup and restore, a performance pass on hot queries, a production compose profile, OpenTelemetry exporter config, and a full regression run.
- **Packaging:** signed Electron builds for Windows, macOS and Linux, auto-update, and a first-run onboarding tour.
- Optional voice input (push-to-talk, local speech-to-text when available).

---

## 7. EVENT SCHEMA

```json
{
  "event_id": "evt_...",
  "event_version": 1,
  "organization_id": "org_...",
  "run_id": "run_...",
  "task_id": null,
  "agent_id": "agent_...",
  "correlation_id": "...",
  "sequence": 42,
  "event_type": "tool.execution.started",
  "timestamp": "2026-11-26T14:00:00Z",
  "source_runtime": "native",
  "payload": {}
}
```

Event types (add each one only when the feature that emits it exists):
`run.created|started|paused|resumed|completed|failed|cancelled`,
`agent.started|message|stream|code|delegated|waiting|completed|failed`,
`plan.proposed|approved|rejected`,
`task.created|assigned|started|completed|failed`,
`tool.execution.started|completed|failed`,
`approval.requested|approved|rejected`,
`pr.opened|reviewed|merged|closed`,
`checkpoint.created`, `artifact.created`, `memory.updated`,
`connection.state_changed`, `browser.connected|disconnected|session.expired|waiting_for_user|resumed`,
`provider.response.received`, `system.health`, `emergency_stop.engaged|cleared`.

Rules:
- `sequence` is monotonic per run.
- Payloads are validated against JSON Schema and secret-redacted.
- Schemas live in `packages/event-schemas` and generate both the Pydantic and the TypeScript types.
- High-frequency stream events (`agent.stream`, `agent.code`) may be sent to clients without being persisted one by one. The final content is persisted in the completion event.

---

## 8. GUI SPECIFICATION

The GUI is the product's main differentiator. Treat it with the same rigor as the backend.

### 8.1 Design system

- **Tokens:** CSS variables (`--nx-*`) for every color, radius, shadow, spacing step and z-index. **Components never use hard-coded palette classes** (`bg-slate-950`, `text-white`, raw hex values). An ESLint rule enforces this.
- **Themes:** dark and light from Phase 1, then high-contrast plus 3 accent themes by Phase 6. Themes switch at runtime and persist. Terminal and code-highlighting themes follow the active theme.
- **Type:** IBM Plex Sans Arabic for UI text (covers Arabic and Latin), JetBrains Mono for code, plus one display face for the Command Bridge only.
- **Tone:** a calm, dense, professional operations console everywhere **except** the Command Bridge, which is deliberately cinematic.
- **Motion:** purposeful and short. Everything respects `prefers-reduced-motion`, and animations pause while the tab is hidden.
- **States:** every screen and data region has explicit loading (skeletons), empty (with the next action), error (with retry) and offline states.

### 8.2 RTL, i18n, accessibility (enforced from Phase 1)

- Languages: **Arabic (default), English, Persian.** Set `<html dir>` and `lang` from the active language.
- **Logical properties only:** `ms/me/ps/pe/start/end/inset-inline`. ESLint fails the build on `ml-/mr-/pl-/pr-/left-/right-/text-left/text-right`.
- Arrow-key navigation in tabs, menus, lists and carousels mirrors in RTL. Directional icons (arrows, chevrons) flip.
- **LTR islands:** code, paths, branch names, URLs, terminals, JSON/YAML and model names always render `dir="ltr"`.
- Locale-aware numbers, dates and relative times.
- A test fails if any translation key is missing in any locale. Playwright takes RTL and LTR screenshots of every main page.
- Accessibility: skip-to-content link, visible focus rings, full keyboard operation, ARIA roles on all custom controls, focus-trapped dialogs that close on Escape, `aria-live` toasts, WCAG AA contrast in every theme, and axe checks in Playwright.

### 8.3 Screens

Each screen appears only in the phase where it works. The phase is shown in brackets.

**A. Command Bridge [3] — signature screen (from AATM)**
- A full-screen "starship bridge". Each worker is an animated SVG robot at its own station, colored by the agent's avatar color. The robot has states: idle, writing, thinking, needs human, done.
- A live mini-screen above each robot shows the code or text the agent is producing, line by line, highlighted, with its branch and PR number.
- The manager stands in the center on a hologram, with stage lights for the mission phases (plan → build → review → merge).
- HUD chips: crew online, connection health per kind, mission name, mission timer, live-stream state.
- A commander console docked at the bottom: send directives, approve or reject inline, global emergency stop (with confirmation).
- Clicking a station opens a Focus view: pause/resume, stop, replace, open workspace, open live browser, cost/usage (only if reported).
- An onboarding strip shows when there is no connection, no repository or no directive yet, and never covers the stations.
- Mobile: a list of station cards, each with the last lines of output.

**B. Agent Workspace [5] (from OpenHands)**
- Tabs per agent: **Terminal** (xterm, read-only stream of the sandbox shell), **Files** (tree + Monaco viewer), **Changes** (diff viewer with commit list and uncommitted changes), **Git bar** (branch, pull, push, open PR, with approval where required), **Browser** (see C), **Planner** (current sub-tasks and todo list).

**C. Live Browser panel [1] (from DeerFlow) — essential for the browser connection**
- Shows the live view of an agent's browser tab (Section 6, Phase 1, bridge item "Live view stream"), with the tab title, URL bar, back/forward and tab switcher.
- The owner can click, scroll, type and navigate from inside NEXUS. The panel shows connection state and reconnects automatically.
- It opens automatically on `WAITING_FOR_USER` with the banner "This agent needs you" and a **Resume** button. NEXUS never interacts with the verification itself; only the human does.
- It also offers a "Focus the real tab" button.

**D. Chat [2] (from AgentScope + DeerFlow + OpenHands)**
- Streaming Markdown with code highlighting, Mermaid, math and tables, and correct mixing of Arabic and Latin text. Everything is sanitized.
- **One renderer per tool:** Bash, Read, Write, Edit (with inline diff and +/− stats), Grep, Glob, HTTP, AskUser, TaskCreate, plus a default renderer. Tool cards collapse, and show duration and status.
- Plans and operational steps are shown; chain-of-thought is not (Section 3.2).
- Inline human-input and approval cards inside the conversation.
- Attachments (drag and drop, paste images). An artifacts drawer previews images, Markdown, CSV tables, HTML (sandboxed iframe), PDF and Office files.
- **Virtualized message list** that sticks to the bottom, a conversation outline, search inside the conversation, cancel/stop, and a queue indicator when a browser tab is busy.
- Projects, recent chats, export, trash with restore.

**E. Studio / Team Builder [4] (from AutoGen Studio + ChatDev)**
- @xyflow/react canvas with a component library sidebar (agents, teams, tools, connections, nodes), drag and drop, right-click menus, full undo/redo history, auto-layout, minimap.
- **Forms generated from JSON Schema** for every component (validated with Ajv), so no hand-written form per node type.
- Two-way synced JSON/YAML editor in Monaco, server-side validation with errors pinned to nodes, a **Test drawer** that runs on a sample input, and a gallery of templates.

**F. Live Agent Flow graph [3] (from AutoGen Studio + CrewAI)**
- During a run, a dagre/elk-laid-out graph of agents. Animated edges carry messages, and clicking an edge lists the messages exchanged.
- The node drawer shows config, instructions and version, with an **Open in IDE** button (VS Code / JetBrains / auto-detect).
- Zoom and fit, export to PNG and PDF.

**G. Runs, Traces & Observability [2 → 6] (from CAMEL's log viewer + OpenHands)**
- Run timeline (event list with filters), per-agent traces, filterable and paginated log table with a detail side panel.
- Metrics per connection (Phase 6). Usage and cost are shown only where reported.
- Import an exported run file to inspect it offline.

**H. Command Center [2], Missions & Tasks [3], Approvals [2], PRs [3], Org map [3], Audit [6], Settings [1 → 6]**
- KPI cards with real counts only, kanban board, approvals inbox with badges in the navigation, PR list with review verdicts, system health (CPU/RAM/disk, bridge, workers, sandbox).

**I. Connections & Profiles [1]**
- Browser devices, profiles and tabs with state, owning agent, userscript version, queue, last error.
- Actions: pair, revoke, rotate credential, open live browser, selector test, adapter editor, terms confirmation status.
- Local models list with a pull button. The API connection stays hidden until it is enabled in Settings.

**J. Productivity [1 → 7]**
- Command palette (Ctrl/Cmd+K) for every action and screen [1], scheduled tasks with calendar [6], first-run onboarding tour [7], optional voice input [7].

### 8.4 Frontend architecture rules

- Feature-based structure: `src/features/<feature>/{components,hooks,api,store,types}`. **No file over ~300 lines** for pages and ~400 for anything else. Split instead.
- **No god components.** The app root only does providers and routing. Each screen owns its data through TanStack Query hooks (`useAgents()`, `useTasks(missionId)`, …).
- **Targeted live updates:** each WebSocket event updates or invalidates only the queries it affects. Never refetch everything on every event. High-frequency streams (`agent.stream`, `agent.code`, live-view frames) go to dedicated stores, never into the query cache, and render through `requestAnimationFrame` batching.
- **Stream isolation:** every stream is keyed by `(agentId, runId, messageId)`. Never use a shared or global "current message".
- Typed API client generated from the backend OpenAPI. Runtime validation of WebSocket events with Zod.
- No `any` outside documented boundary files.
- No dead code, no commented-out UI, no `v-if="false"`-style hidden features.

---

## 9. QUALITY GATES

`scripts/check.sh` must run and pass before a phase is declared done:

- **Python:** ruff, mypy (strict on `app/core`, `app/runtimes`, `app/connections`, the bridge), pytest.
- **TypeScript:** eslint (including the RTL and hard-coded-color rules), `tsc --noEmit`, vitest.
- **Userscript:** build, adapter schema validation, unit tests.
- **i18n:** missing-key check for ar, en, fa.
- **E2E:** Playwright against the running app + mock provider, including RTL screenshots and axe checks.
- **Migrations:** `alembic upgrade head` on an empty SQLite **and** an empty PostgreSQL database, and `downgrade -1` for the latest migration.
- **Startup check:** backend health endpoint, worker heartbeat, bridge health.

Never mark a test as skipped to make the suite green without recording why in the log.

---

## 10. REPOSITORY LAYOUT (create folders only when they get real content)

```
nexus-agent-os/
  apps/
    web/                  # React + Vite frontend
    desktop/              # Electron shell
    backend/              # FastAPI modular monolith
      app/
        api/ core/ auth/ organizations/ agents/ teams/ workforce/ software_team/
        workflows/ runtimes/ connections/ tools/ events/ messaging/
        memory/ knowledge/ mcp/ approvals/ schedules/ sandbox/
        analytics/ audit/ db/
      migrations/
      tests/
  workers/
    execution/
  integrations/
    userscript/
      src/core/ src/security/ src/providers/
      adapters/           # <provider>.yaml + schema
    browser-bridge/
    mock-provider/
  packages/
    contracts/            # workflow + API + adapter schemas
    event-schemas/
    ui/                   # design tokens + shared components
  infrastructure/
    docker/
  docs/
  scripts/
  docker-compose.yml
  .env.example
```

---

## 11. REQUIRED DOCUMENTATION

Keep these current, and update them at the end of every phase:

- `docs/IMPLEMENTATION_STATUS.md`:

| Feature | Status (Complete / Partial / Not started / Blocked) | Implementation path | Tests | Notes |
|---|---|---|---|---|

- `docs/DEVELOPMENT_LOG.md`, per session: environment, work done, decisions, reused code, new dependencies, tests run with results, known issues, next step.
- `docs/TECHNICAL_DECISIONS.md`, `docs/SOURCE_CODE_REUSE_AUDIT.md`, `docs/DEPENDENCY_AUDIT.md`, `docs/SYSTEM_DESIGN.md`.
- `docs/PROTOCOL.md`: bridge ↔ userscript and backend ↔ bridge protocol, with message schemas, states, commands and close codes.
- `docs/ADAPTERS.md`: how to write and test a provider adapter YAML.
- `docs/INSTALL.md`, `docs/DEVELOPMENT.md`, `docs/DEPLOYMENT.md`, `docs/security/SECURITY.md` (threat model for the bridge, the userscript and the live view), OpenAPI generated from FastAPI.
- `docs/UI_GUIDE.md`: tokens, RTL rules, component patterns, screenshots of each screen in Arabic and English.

---

## 12. START

1. Inspect the working directory and environment (Section 1.1).
2. If `docs/DEVELOPMENT_LOG.md` exists, continue from its "next step".
3. Otherwise begin Phase 0, then Phase 1.
4. Execute only the phase you were asked for, **unless the owner says "run all"**. In that case work autonomously from Phase 0 to Phase 7 without waiting: after each phase run `scripts/check.sh`, update the status documents, commit, and go straight on to the next one. Stop only under the conditions in Section 1.3. At the end, run `scripts/check.sh`, update the status documents, commit, and report:
   - what now works, and how to try it,
   - what was tested,
   - what is partial or blocked, and why,
   - screenshots of new screens in Arabic (RTL) and English (LTR),
   - the recommended next step.

---

## 13. AUTONOMY MODES (the owner decides how much runs unattended)

### 13.1 Levels

| Level | Name | Plans | Tool calls | Merges / PRs | Sandbox network | Unattended |
|---|---|---|---|---|---|---|
| 0 | Manual | owner approves | each call asked | owner merges | off | no |
| 1 | Assisted | owner approves | policy: risky calls asked | owner merges | off | short runs |
| 2 | Autopilot | auto-approved | policy: only irreversible calls asked | auto-merge on pass + green checks | allow-list | yes |
| 3 | Full-auto (**default**) | auto-approved | everything allowed | auto-merge | open | yes, 24/7 |

The level is set globally and can be overridden **per team, per mission and per agent**. The current level is always visible in the header, with a one-click switch.

### 13.2 Action policy (replaces hard-coded approval rules)

- An **action policy** is an ordered list of rules: `allow | ask | deny` by tool, path glob, host, command pattern and agent. The first match wins. It is stored per level, shown in a policy editor, validated, and versioned. Every decision is written to the audit log.
- **Defaults:** Level 3 ships as "allow all inside the sandbox". For actions that leave the sandbox, it ships with a short `ask` list (force-push to a protected branch, deleting files outside the workspace, payments, sending external messages), because those cannot be undone. The owner may edit or empty this list. Emptying it requires typing a confirmation phrase once.
- **Host execution:** a switch in Level 3 lets agents run code on the host instead of the sandbox. It is off by default, and turning it on requires the same confirmation phrase.
- **Budgets:** steps, time, tool calls, workers and requests per hour are all configurable. `0` means unlimited. A watchdog tracks them and shows them live.
- **Loop detection** stays on. The action on detection is configurable: warn, replan, or stop.

### 13.3 Autopilot behavior (what "no restrictions" means in practice)

- **Unattended operation:** missions run without the app in the foreground. Workers, the bridge and the browser profiles are supervised and restarted after a crash. A run resumes from its last checkpoint. Add self-heal (as AATM's `self_heal.py` does) for stuck states.
- **A blocked tab never blocks the mission.** When a tab goes to `WAITING_FOR_USER`, `RATE_LIMITED` or `SESSION_EXPIRED`:
  1. its queued work moves to the **fallback chain** the owner configured for that agent (another tab or profile, a local model, or an API connection). Nothing switches silently outside that chain;
  2. NEXUS sends a desktop notification and sound, and opens the Live Browser panel on that tab;
  3. the tab resumes automatically when the human clears the problem.
- **Profile pool autoscaling** (as AATM's `autoscale.py` does): the owner signs in to as many browser profiles as they want. NEXUS assigns tasks across the pool, starts or parks profiles by queue depth, and shows per-profile load. Parallelism comes from more tabs, never from overlapping requests on one tab.
- **Adapter self-repair:** when `SELECTOR_NOT_FOUND` occurs, an agent proposes a fixed adapter YAML, runs `selector_test` against the live page, and applies the fix automatically only if every selector passes. The change is saved as a new adapter version that can be rolled back.
- **Auto-everything where the level allows:** plan approval, retries, replanning, reviewer JSON-verdict retry, PR creation, auto-merge, schedule-triggered missions, and a nightly report of what ran.
- **Notifications:** a desktop push, a sound and a system-tray badge for anything that needs a human. The owner chooses which events notify.

### 13.4 Definition of Done additions (tests)

- Level 3: a mission with 10 tasks completes with zero approval prompts, inside the sandbox, from a single directive.
- A tab forced into `WAITING_FOR_USER` does not stop the mission: its tasks move to the fallback chain, a notification fires, and the tab resumes automatically after the mock verification is cleared by a test "human".
- The profile pool scales from 1 to N tabs under queue pressure, and no tab ever has two requests in flight.
- Adapter self-repair: a mock layout change is fixed automatically and the fix is rolled back on request.
- The kill switch stops everything within 2 seconds in every level.
- A test proves the bridge never touches cookies, never rotates identity and never interacts with the mock verification screen.
- Emptying the `ask` list requires the confirmation phrase.

---

## 14. FULL AUTOMATION DIRECTIVE (default behavior of NEXUS at runtime)

NEXUS is built to be **zero-touch**. The owner gives one directive, and NEXUS delivers a finished, verified result. The system must be designed, tested and tuned for this, not merely allow it. This section tells every runtime, agent and UI how to behave by default. The hard lines in Section 3.1 stay in force.

### 14.1 Principle

One directive in, finished result out. Everything in between (planning, assignment, coding, testing, review, fixing, merging, reporting) happens without the owner. The owner can watch, steer or stop at any moment, but is never required to act.

### 14.2 Zero-touch pipeline

`directive → plan (auto-approved) → task DAG → assign to workers → build in sandbox or agent mode → run tests → open PR → review → fix loop → merge → verification → report`

- Each stage advances automatically to the next one. No stage waits for a human, except the cases listed in 14.3.
- The fix loop runs until the reviewer and the tests pass, or until the replan budget is spent (14.4).
- Independent tasks run in parallel across the profile pool and the local/API connections (Section 13.3).

### 14.3 The only reasons to wait for a human (exhaustive list)

1. A tab reports `WAITING_FOR_USER` (CAPTCHA, verification, login wall, terms prompt). Only that tab waits (Section 13.3).
2. An action that matches an `ask` rule in the owner's action policy (Section 13.2).
3. The owner pressed the kill switch or paused the mission.

Everything else is decided by the system.

### 14.4 Decide, don't ask

- Agents make a reasonable decision and record it in the mission log. They do not ask the owner. When a directive is ambiguous, state the assumption, proceed, and flag the assumption in the final report.
- A failed review triggers an automatic fix. Repeated failure triggers a replan with a different approach. If the replan budget is exhausted, park that task, continue every other task, and list it in the report. Do not stop the mission.
- A crashed worker, bridge or profile is restarted. The run resumes from the last checkpoint.

### 14.5 Done means verified

- At plan time, write **acceptance criteria** for the mission. A separate verifier agent checks the finished result against them, using tests, running the app, or reading files. A mission is "done" only when the verifier passes.
- Detect stuck missions (no progress across N steps) and change strategy automatically: replan, switch worker, or split the task.

### 14.6 Triggers and background operation

- Start missions from the UI, a chat message, a schedule, a file-watch rule, or a local git event (a new commit, a new issue file).
- Missions run with the app minimized or closed to the tray. The owner gets a desktop notification only for 14.3 events and for mission completion.
- A **daily digest** summarizes what ran, what was merged, what is parked, and what needs the owner.

### 14.7 Definition of Done additions (tests)

- From one directive, a mock mission goes through the whole pipeline (plan → PR → review → fix → merge → verification → report) with zero owner clicks.
- An ambiguous directive proceeds on a stated assumption and the assumption appears in the report.
- A forced reviewer failure is fixed automatically. Repeated failure triggers a replan, and when the replan budget is exhausted the task is parked while other tasks finish.
- A crashed worker is restarted and the run resumes from its checkpoint.
- A schedule trigger and a file-watch trigger each start a mission that completes unattended.
- The verifier rejects a result that does not meet the acceptance criteria and sends the mission back for another pass.

---

## APPENDIX A — GUI RESEARCH ALREADY DONE (12 reference projects)

Findings come from reading the source of each repository (shallow clones, November 2026). Use them as design input. Re-verify any detail before copying code, and respect licenses (Section 3.4).

| Project | GUI found in source | Take | Avoid |
|---|---|---|---|
| **OpenHands** | Full React 19 app (~207k lines) + Electron; xterm terminal, browser tab, diff viewer with commits, git control bar, command menu, automations; 16 languages; 7 color themes; ~1,000 test files | Agent workspace tabs, git bar, diff viewer, theme system, Electron packaging, test discipline | Arabic is fully translated and `dir="rtl"` is set, but layout uses ~330 physical-direction classes and only ~1 logical one, so RTL does not mirror properly |
| **DeerFlow** | Next.js 16 app (~121k lines) + landing/docs; **live browser view with owner input** (click/move/wheel/key/text/navigate/tabs); virtualized message list; command palette; projects, scheduled tasks, usage, trash, sharing, voice; ~500 test files | Live Browser panel, virtualization, command palette, productivity screens | No RTL languages |
| **AgentScope** (`examples/web_ui`) | React 19 + shadcn + Tailwind 4 (~41k lines); streaming Markdown with Mermaid/math; **per-tool renderers** (Bash/Edit/Grep/Read/Write/Diff); artifact drawer with Office preview; voice (VAD/WebRTC); schedule calendar; knowledge bases; onboarding tour | Chat rendering, tool renderers, artifacts drawer | Lives under `examples/`; no tests |
| **AutoGen Studio** | Gatsby + Ant Design + Tailwind (~28k lines); drag-and-drop team builder with **undo/redo**, Monaco, validation, test drawer; live **agent-flow graph** (dagre); MCP playground; gallery | Builder UX, flow graph, MCP playground | Aging Gatsby stack, two mixed UI kits, no i18n, no tests |
| **ChatDev** | Vue 3 + vue-flow (~18.6k lines); visual workflow editor with right-click menus; **schema-driven form generator**; pixel-sprite characters animated on nodes during runs; batch-run page | Schema-generated forms, context menus, playful run visualization | 3,700-line single-file page, dead code (`v-if="false"`, `|| true`), read-only YAML view, no tests |
| **AATM** | React 18 + Tailwind (~17k lines); **Command Bridge** with animated SVG robots and live code screens per agent, manager hologram, emergency stop; **best RTL** (74 logical classes, 0 physical); ar/en/fa; skip link, keyboard tabs, reduced motion | Command Bridge concept, RTL discipline, accessibility basics, the connector protocol | `App.tsx` with ~30 state variables refetching 23 endpoints on every live event; 268 `any`; ~546 hard-coded palette classes patched with `!important` in light mode (dark `bg-slate-950` cards remain); chat shown as plain text without Markdown; unsanitized SVG via `dangerouslySetInnerHTML` |
| **CrewAI** | Single-page flow visualizer (vis-network canvas, ~3.6k lines): glow/scale animations, node drawer with highlighted source, **Open in IDE**, dark mode, PNG/PDF export | Node drawer, Open in IDE, export | Unpinned CDN dependency (`lucide@latest`); viewer only, no run UI |
| **CAMEL** | Gradio demo apps + standalone `camel_log_viewer.html` (~1.8k lines): cost calculation, charts, agent traces, drag-and-drop log folder | Offline run/log inspector | Gradio demos are not a product UI |
| **Agno** | Streamlit helpers (session selector, tool-call expanders, chat export) + cookbook pages; official UI is hosted outside the repository | Session-management patterns | Nothing to reuse as a GUI |
| **MetaGPT** | ~150-line Chainlit example + ~300-line Streamlit SPO app | — | A **global message variable shared by concurrently running roles**, so streams interleave; hard-coded outdated model list |
| **LangGraph** | No GUI; only Mermaid/PNG graph drawing for notebooks; Studio is hosted externally | Use for workflow runtime only | — |
| **OpenManus** | No GUI (CLI `input()` prompt) | — | — |
