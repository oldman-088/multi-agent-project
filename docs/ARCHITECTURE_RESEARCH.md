# Architecture Research (Phase 0)

Date: 2026-11-26. Every claim below cites a file I actually opened, in the shallow clones under
`research/repos/` (excluded from git). Paths are relative to each repository root.

## 1. Repositories and commit SHAs

| Project | URL | Commit SHA | Top-level license |
|---|---|---|---|
| AATM | https://github.com/oldman-088/AATM | `e90f2efa618e575698ccb1195f7049da2a60a976` | **No LICENSE file** (only `THIRD_PARTY_NOTICES.md`) |
| OpenHands (Agent Canvas frontend) | https://github.com/All-Hands-AI/OpenHands (now `OpenHands/OpenHands`) | `be48abe2585a01b4ee666e71ba5c43c47fb63772` | MIT |
| OpenHands software-agent-sdk | https://github.com/OpenHands/software-agent-sdk | `7cfef13a0aaf967d192b1db5e01ace609863dcce` | MIT |
| DeerFlow | https://github.com/bytedance/deer-flow | `349540c13fbebb03b8bc1e3fd03d913682900751` | MIT |
| AgentScope | https://github.com/agentscope-ai/agentscope | `7167d2a2d4167fde92f83f410be09d89eb208446` | Apache-2.0 |
| AutoGen | https://github.com/microsoft/autogen | `8390985108cb1e3881f5f7297765758d8ad2540c` | `LICENSE` = CC-BY-4.0 (docs); `LICENSE-CODE` = MIT (code) |
| ChatDev | https://github.com/OpenBMB/ChatDev | `464a681ba7bda869db97a50c5fa707c9a0fb57a0` | Apache-2.0 |
| CrewAI | https://github.com/crewAIInc/crewAI | `77237aecacb204684a80e334dcd8eefa90d7ee60` | MIT |
| CAMEL | https://github.com/camel-ai/camel | `c9f270d06b80d408809ff4553557a7f5ec4aef64` | Apache-2.0 |
| Agno | https://github.com/agno-agi/agno | `e58381bc1d795840fc06fb11d30fa6a1994cdd94` | Apache-2.0 |
| MetaGPT | https://github.com/FoundationAgents/MetaGPT | `11cdf466d042aece04fc6cfd13b28e1a70341b1f` | MIT |
| LangGraph | https://github.com/langchain-ai/langgraph | `3e3dbd42c5329dd404669ccd923c005c814bee3a` | MIT |
| OpenManus | https://github.com/FoundationAgents/OpenManus | `3309bf4e416fb1c74b008f3e86494439a31bad53` | MIT |

Per-directory licenses found (via `find -iname 'LICENSE*'`, depth ≤ 4):

- AutoGen: every package under `python/packages/*/LICENSE-CODE` (MIT); the root `LICENSE` is CC-BY-4.0 and covers documentation only.
- LangGraph: `libs/{langgraph,checkpoint,checkpoint-sqlite,checkpoint-postgres,prebuilt,cli,sdk-py}/LICENSE` (MIT).
- Agno: `libs/agno/LICENSE`, `libs/agnoctl/LICENSE`, `libs/agno_infra/LICENSE`.
- DeerFlow: separate licenses under `examples/deerflow-extension-*/LICENSE` and `skills/public/*/LICENSE.txt`. Those must be checked individually before any reuse; I did not read them.
- CAMEL: `licenses/license_template.txt` (file header template, not a different license).

**Note on OpenHands.** The `OpenHands/OpenHands` repository is now only the "Agent Canvas" React frontend. Its `AGENTS.md`
(table "Repository Ownership") says that events, agents, tools and the REST/WebSocket API live in
`OpenHands/software-agent-sdk`, so I cloned that repository too to answer the Phase 0 questions.

## 2. AATM

### 2.1 Connector protocol (`bridge/connector.py`)

Transport: one WebSocket per browser profile at `WS /v1/connector`. The admin HTTP API is
`PUT/DELETE /v1/connector/profiles/{id}`, `POST .../reset`, `POST .../command`, `GET /v1/connector/profiles[/{id}]`,
protected by a static bearer `ARENA_BRIDGE_TOKEN` (`_require_admin_bearer`, compared with `hmac.compare_digest`).

**Hello / auth (`handle_socket`, `_authenticate`).**
1. The server accepts the socket and waits ≤ `HELLO_TIMEOUT_SECONDS = 10` for the first text frame. On a timeout or invalid JSON, it closes with **4400**.
2. Userscript → bridge: `{"type":"hello","profile_id","token","page_origin","script_version"}`.
3. If the `profile_id` is unknown, the socket closes with **4404** (`CLOSE_NOT_REGISTERED_YET`).
4. The token is SHA-256 hashed and compared with `hmac.compare_digest` against the registered hash.
   `page_origin` must be in the profile's `allowed_origins`, and the WebSocket `Origin` header must equal `page_origin`. Non-loopback origins also need
   `real_enabled` on the profile **and** `ARENA_CONNECTOR_ENABLED=true` in the bridge process. Any failure closes with **4401**.
5. When a second connection arrives for the same profile, the old socket closes with **4409** ("replaced by a newer connection").
6. Bridge → userscript `config`: `{type:"config", profile_id, dom, stop_selectors, stop_phrases, reply_timeout_seconds, status, mode, commands, offline_selectors, offline_phrases}`.
   Selectors are therefore **sent as data**, which is the precursor of NEXUS "adapters as data".

**Close codes:** 4400 (bad or missing hello), 4401 (auth, token or origin refused; also sent on re-registration with a changed token or origin), 4404 (not registered yet),
4409 (replaced), 4410 (unregistered). In `backend/app/browser/arena_connector.py` (the userscript body, `socket.onclose`), 4401 and 4410 cause a 60 s retry,
4409 causes a 300 s retry, and other codes use exponential backoff from 2 s up to a 30 s cap.
There is **no** dedicated close code for "script too old": `_valid_repo` raises the error `script_outdated` (HTTP 409) only for repository commands.

**Message types, userscript → bridge (`_on_message`):** `status` (`ready|busy|needs_human`), `needs_human` (reason),
`state` (agent page state), `event` (`kind`, `detail`; e.g. `keep_working_clicked`, `tab_hidden`, `tab_visible`, `error`, `send_failed`),
`result` (`request_id`, `ok`, `data` | `code`, `message`), `answer` (`request_id`, `text`, capped at 200,000 characters), `error` (`request_id`, `code`, `message`).
**Bridge → userscript:** `config`, `prompt` (`request_id`, `prompt`), `command` (`request_id`, `command`, `args`), `resumed`.

**Commands** (`AGENT_COMMANDS`): `new_session, submit, keep_working, stop, read_last_reply, selector_test, select_repo, create_pr, close_feedback`.
Read-only commands: `read_last_reply, selector_test`. Safe while stopped: `stop`. Validation (`_validate_command`):
- `submit` needs non-empty text of at most `MAX_PROMPT_CHARS = 120_000`.
- `repo` must match `owner/name` and needs script ≥ 2.1.0.
- `new_session` URLs must be on an allowed origin.

**States** (`AGENT_STATES`): `ready, generating, idle, keep_working_visible, tool_call_limit, pr_ready, needs_human, offline`.
The profile `status` is separate: `offline | ready | busy | needs_human`.

**Concurrency:** one `asyncio.Lock` per profile (`dispatch` and `command` both use `async with state.lock`). A waiting caller blocks on the lock.
There is no visible queue, no position report, and no reorder or cancel.

**Needs-human handling (`_mark_needs_human`):** the profile is marked, the state is persisted (`_save`) so it survives a restart, and pending chat
requests fail with 409 while agent commands keep waiting. Only `reset` (a human action via the admin API) clears it and sends `resumed` to the page.

**Default stop rules** (`DEFAULT_STOP_SELECTORS`, `DEFAULT_STOP_PHRASES`): CAPTCHA, Turnstile, hCaptcha and reCAPTCHA iframes and classes, phrases such as
"verify you are human" and "rate limit", terms prompts and login walls. Offline phrases (`DEFAULT_OFFLINE_PHRASES`) are reported as `offline`, not as needs-human.

**Persistence:** registrations are saved to a JSON state file (mode 0600, atomic replace). It holds only token hashes.

### 2.2 `backend/app/providers/adapters/arena_bridge.py`

This is **not** the WebSocket connector. It is an HTTP client (`ArenaLocalBridgeAdapter`) for an OpenAI-compatible loopback daemon
(`bridge/server.py`, `POST /v1/chat/completions`, `GET /health|/ready`, `/v1/sessions/{id}`). It sends `messages`, `max_tokens`
and `temperature` plus `X-AATM-*` session headers, and parses an OpenAI-shaped completion via `_extract_openai_completion`.
It **estimates** tokens (`self.estimate_tokens(...)`), and `bridge/server.py` has `_estimate_tokens = len // 4`.
NEXUS must not do this: browser-session usage is `null`.
`bridge/server.py` reads the host from `ARENA_BRIDGE_HOST` (default `127.0.0.1`), so it *can* be bound to a non-loopback address.

### 2.3 How completion is detected (`backend/app/browser/arena_connector.py`, userscript body)

- **Chat mode (`handlePrompt`):** it types the prompt, clicks send after 150 ms, then polls every 250 ms. An answer is complete when a new assistant
  message exists, the `busy` selector is absent, and the text stays **identical for ≥ 1000 ms**. The hard timeout is `reply_timeout_seconds` (default 600).
  It checks for a human check on every tick.
- **Agent mode (`computeState`):** a MutationObserver plus a 1 s tick. `needs_human` > `offline` > `pr_ready` (no Stop button and a merge button present) >
  `tool_call_limit` (after `TOOL_LIMIT_SETTLE_MS = 15000`) > `keep_working_visible` > `generating` (Stop button visible) > `idle`
  (no Stop button for `IDLE_MS = 5000` after the last activity) > `ready` (composer found).
- **Userscript metadata (`build_userscript`):** `@grant none`, `@noframes`, `@run-at document-idle`, `@match` limited to the configured patterns.
  **The per-profile token is embedded in the generated script** (`config.token`).

### 2.4 Manager loop (`backend/app/orchestration/manager_arena.py`)

- **Plan DAG validation (`validate_plan_graph`):** tasks reference dependencies by integer index. It rejects unknown, out-of-range and self dependencies, then runs a
  three-colour DFS for cycles. `plan_warnings` flags chains (many tasks depending on one) and Markdown-mangled glob names.
  `missing_shared_contract` flags plans with a frontend task and a backend task that name no common contract file (EN and AR keyword regexes).
  `clarification_question` accepts `{"ambiguous": true, "tasks": [], "summary_ar": "<question>"}` as a valid "ask the owner" answer.
- **Review verdict parsing:** it first tries `extract_manager_json` (in `backend/app/orchestration/arena_prompts.py:750`, not opened).
  If no JSON is found, it sends one retry built by `_json_retry_prompt`, which carries an empty JSON template.
  It then falls back to `review_verdict_from_text`: a `verdict:` field regex, then request-changes markers (EN and AR), then approve markers. It returns `None` rather than invent a verdict, and the job then goes to a human.
  `_review_pr_mismatch` refuses a verdict that names another PR number. `_combine_review_verdicts` gives `request_changes` if any part requests changes.
- **Runtime (`ManagerArenaRuntime` docstring):** one manager prompt in flight, a long-lived session per project, a new session after N exchanges,
  and "the manager never merges".

### 2.5 Security measures present vs. missing (relative to NEXUS §3)

| Present in AATM | Missing / weaker than NEXUS requires |
|---|---|
| Token stored only as SHA-256; constant-time compare | No pairing flow: a long-lived token is **embedded in the userscript file** (leaks if the script is shared); no short-lived session token or heartbeat renewal |
| Origin header must equal the declared `page_origin` and be allow-listed | Admin API uses one static shared bearer (`ARENA_BRIDGE_TOKEN`), not a per-device credential |
| Real-site origins double-gated (profile flag + bridge env) | No per-provider terms-confirmation record with a timestamp |
| One in-flight request per profile | No queue visibility, reorder or cancel; no idempotency key; no `UNCERTAIN_SUBMISSION` handling after a reload |
| needs_human persisted, only a human reset clears it; read-only and stop still allowed | No live-view / takeover channel; no dedicated "script too old" close code |
| Prompts and answers not logged (only ids, lengths, durations) | Selectors are sent as data but there is no versioned, schema-validated adapter file |
| Size limits (120k prompt / 200k answer / 50 events) | `bridge/server.py` host is configurable to non-loopback; token usage is estimated (`len//4`) |
| `@grant none`, `@noframes` | No message-schema validation in the userscript (`JSON.parse`, then type switch) |

## 3. LangGraph (`libs/`)

- **StateGraph:** `libs/langgraph/langgraph/graph/state.py:132` `class StateGraph(Generic[StateT, ContextT, InputT, OutputT])`, with
  `add_node` (overloads at 377–668), `add_edge` (929), `add_conditional_edges` (983) and `compile(..., interrupt_before, interrupt_after)` (1178–1185).
  Version: `libs/langgraph/pyproject.toml` = 1.2.24, Python ≥ 3.10.
- **Checkpointers:**
  - SQLite: `libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/__init__.py:49` `SqliteSaver` and `.../aio.py:49` `AsyncSqliteSaver`
    (`from_conn_string` at 145, `setup` at 317). It creates its **own tables `checkpoints` and `writes`** (aio.py:331, 341). It depends on `aiosqlite>=0.20` and **`sqlite-vec>=0.1.6`** (pyproject).
  - PostgreSQL: `libs/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py:45` `PostgresSaver`, `aio.py:45` `AsyncPostgresSaver` (`from_conn_string` 70, `setup` 95),
    `shallow.py` `ShallowPostgresSaver`/`AsyncShallowPostgresSaver`. Tables `checkpoint_migrations`, `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` (base.py:47–69).
    It depends on **psycopg 3** + psycopg-pool, not asyncpg.
- **Interrupt/resume:** `libs/langgraph/langgraph/types.py:983` `interrupt(value, *, response_schema=None)`. The first call raises `GraphInterrupt`, which
  **requires a checkpointer**. Resuming uses `Command(resume=...)` (`types.py:913`, field `resume` at 937; it accepts a value or a map of interrupt id → value).
  **The node re-executes from its start on resume**, so code before `interrupt()` must be idempotent.
- **Consequence for NEXUS:** the checkpointer manages its own tables and connection (it is not SQLAlchemy). "Same database" means the same SQLite file or Postgres database
  with LangGraph's tables beside ours, created by `setup()`. Alembic must ignore those tables (`include_object` filter). See TD-006.

## 4. OpenHands software-agent-sdk (`openhands-sdk/openhands/sdk/`)

- **Events:** `event/base.py:21` `class Event(DiscriminatedUnionMixin, ABC)` is frozen pydantic (`extra="forbid", frozen=True`) with `id`, `timestamp`,
  `source` and `parent_id`. `LLMConvertibleEvent` (76) marks events that are replayed into the model context.
  - `event/llm_convertible/action.py:39` `ActionEvent`: `source="agent"`, `thought`, `reasoning_content`, `thinking_blocks`, `action`, `tool_name`,
    `tool_call_id`, `tool_call`, `llm_response_id`, **`security_risk`**, `critic_result`, `summary`.
  - `event/llm_convertible/observation.py`: `ObservationBaseEvent` (17, `source="environment"`, `tool_name`, `tool_call_id`), `ObservationEvent` (32,
    `observation`, **`action_id`** links back to the action), `UserRejectObservation` (86, `rejection_reason`, `rejection_source`, `action_id`),
    `AgentErrorEvent` (146, with `validation_errors`).
  - So an action and its observation are separate immutable events linked by `action_id`/`tool_call_id`. NEXUS maps this to
    `tool.execution.started` → `tool.execution.completed|failed` with the same `correlation_id`.
  - Note: `ActionEvent` carries `thought` and `reasoning_content`. NEXUS must **not** forward these to the UI (§3.2).
- **Confirmation policies:** `security/confirmation_policy.py`: `ConfirmationPolicyBase.should_confirm(risk)`, with `AlwaysConfirm`, `NeverConfirm` and
  `ConfirmRisky(threshold=HIGH, confirm_unknown=True)`. Risk levels (`security/risk.py:13`) are `UNKNOWN, LOW, MEDIUM, HIGH`, and comparisons involving UNKNOWN raise.
  In `agent/agent.py:1375–1386` (`_set_confirmation_status`), if any pending action's risk needs confirmation, the conversation transitions to
  `ConversationExecutionStatus.WAITING_FOR_CONFIRMATION` (`conversation/state.py:51–63`) and stops.
  `conversation/impl/local_conversation.py:3445` `reject_pending_actions` turns each unmatched action into a `UserRejectObservation` and returns to IDLE.
  Risk is self-reported by the model (`_extract_security_risk` pops `security_risk` from the arguments) and can be overridden by a `SecurityAnalyzer` (`security/analyzer.py`, not opened).
- **Consequence for NEXUS:** the Tool Gateway approval hook copies this shape: a per-agent policy (`always | never | risky(threshold)`), with risk taken from the **tool's
  declared metadata** rather than trusted from the model, and rejection recorded as an event the runtime feeds back as an observation.

## 5. CAMEL Workforce (`camel/societies/workforce/`)

- **Decomposition:** `workforce.py:1549` `_decompose_task`. In `PIPELINE` mode it does not decompose (it uses predefined tasks). Otherwise it formats
  `TASK_DECOMPOSE_PROMPT` with the task content and `_get_child_nodes_info()` (the worker roster), resets `task_agent` and calls `task.decompose(...)`
  (streaming is supported), then `_update_dependencies_for_decomposition`.
  Assignment: `_find_assignee` (4042) assigns a batch of tasks to the workers with the best capabilities, waiting up to 2 s for workers to become ready.
  `_create_worker_node_for_task` (4186) can spawn a new worker. Tasks flow through a `TaskChannel` (`task_channel.py:85`, a hash map plus a status index).
- **Failure handling:** `_handle_failed_task` (4642). `FailureHandlingConfig` (`utils.py:227`) has `max_retries` (default 3), `enabled_strategies`
  (None = all, with LLM analysis; [] = none; a single entry is applied without analysis) and `halt_on_max_retries`.
  `RecoveryStrategy` (`utils.py:211`) is `RETRY, REPLAN, DECOMPOSE, CREATE_WORKER, REASSIGN`.
  A task explosion guard halts when pending tasks exceed `MAX_PENDING_TASKS_LIMIT = 20` (`workforce.py:128`).
  PIPELINE mode simply re-opens and re-posts the task.
- **Consequence for NEXUS (Phase 3):** use explicit recovery strategies with per-mission config, a pending-task cap, and a deterministic order
  (retry → replan) rather than always asking an LLM to choose. Hard caps follow §3.2.

## 6. Not inspected (explicitly)

- AATM: `backend/app/orchestration/arena_prompts.py` (`extract_manager_json`), `arena_agent.py`, `arena_runner.py`, `review.py`, `merge_queue.py`,
  most of `bridge/server.py` (only the header and host binding), the frontend, `bridge/tests`, `bridge/mock_arena/*.html`.
  I only grepped selected regions of `arena_connector.py`: metadata, `handlePrompt`, `connect`/`onclose` and `computeState`.
- LangGraph: the internals of interrupt matching, `checkpoint-conformance`, the CLI and SDKs, and the full `compile()` body.
- OpenHands: the Agent Canvas frontend (Appendix A GUI findings were not re-verified), `security/analyzer.py`, the agent server and the workspace sandbox.
- CAMEL: decomposition prompt text (`prompts.py`), `_analyze_failure` LLM path, `single_agent_worker.py`, `events.py`, logger/metrics.
- DeerFlow, AgentScope, AutoGen, ChatDev, CrewAI, Agno, MetaGPT, OpenManus: only the top-level and per-directory license files.
  The Appendix A GUI findings were taken as given, as the spec instructs, and were **not** re-verified.
- No code from any project was executed.
