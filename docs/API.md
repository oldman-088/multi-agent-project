# NEXUS AGENT OS — REST API contract

> **Owner:** Worker 1 — Backend Engineer (AATM-e7410b2b).
> **Source of truth:** [`docs/SPEC.md`](./SPEC.md). This file is the single shared contract between
> the backend and the frontend; there is no second contract file.
> **Generated reference:** the live OpenAPI document is served at `/openapi.json` and the browsable
> reference at `/docs`. A test (`tests/test_backend_spec.py::test_audit_schema_matches_spec_contract`)
> fails if any `/api/...` route in the OpenAPI document is missing from this file.

---

## 1. Conventions

| Topic | Rule |
|---|---|
| Base URL | All routes are mounted under `/api` (the health probe is also available at `/health`). The frontend uses relative `/api/...` URLs only — never `localhost`/`127.0.0.1` (AGENTS.md frontend rules). |
| Auth | `Authorization: Bearer <access_token>` on every route except the public ones listed in §2. Missing/invalid credentials return **401**; an authenticated user without the required role returns **403**. |
| Organization | The caller's organization is taken from the access-token `org` claim. Send `X-Organization-Id` to override it (must be an organization the user belongs to). |
| Content type | `application/json` for requests and responses. |
| IDs | Opaque, prefixed strings: `usr_`, `org_`, `agt_`, `agv_`, `run_`, `evt_`, `tcl_`, `apr_`, `aud_`, `ckp_`, `conn_`, `cred_`, `dev_`, `prf_`, `bsess_`, `adp_`, `msn_`, `tsk_`, `pr_`, `rev_`. Never parse them; treat them as opaque. |
| Timestamps | ISO-8601 with an explicit UTC offset (`2026-11-27T12:31:56+00:00`). |
| Pagination | `limit` (1–200, default 50) and `offset` (≥0) query parameters. List responses that paginate use `{"items": [...], "total": 0, "limit": 50, "offset": 0}`. |
| Correlation | Every response carries `X-Request-Id`. Audit rows store it. |
| Locales | `ar` (default), `en`, `fa`. |
| Honesty rules | Usage/cost are `null` unless a connection reports them. Capability values are only `supported`, `partial`, `unsupported`, `not_verified`. |

### 1.1 Error envelope

Every non-2xx response — validation, authentication, domain and server errors alike — uses:

```json
{
  "error": {
    "code": "not_found",
    "message": "Agent not found",
    "details": {"agent_id": "agt_123"}
  }
}
```

| HTTP | `error.code` | When |
|---|---|---|
| 400 | `bad_request` | A request the domain cannot interpret. |
| 401 | `unauthenticated` | No credentials supplied. |
| 401 | `invalid_token` / `token_expired` / `wrong_token_type` | Bearer token rejected. |
| 401 | `invalid_credentials` | Wrong email or password (identical for unknown accounts). |
| 401 | `account_locked` | Too many failed logins; `details.locked_until` is set. |
| 401 | `token_revoked` | A rotated refresh token was replayed (all tokens are revoked). |
| 403 | `forbidden` | Role lacks the permission. |
| 403 | `tool_not_allowed` | Tool is not in the agent's allow-list. |
| 403 | `host_not_allowed` | HTTP GET outside the allow-list. |
| 403 | `no_organization` | The user belongs to no organization. |
| 404 | `not_found` | Unknown id **or an id from another organization** (no existence leak). |
| 409 | `conflict` / `already_initialised` / `slug_taken` / `agent_disabled` / `illegal_transition` / `approval_not_pending` / `terms_not_acknowledged` / `device_revoked` / `dependencies_unfinished` / `task_not_claimable` / `last_owner` / `provider_disabled` / `checks_not_green` / `human_approval_required` / `emergency_stop_engaged` / `emergency_stop_unchanged` | A state conflict. |
| 422 | `validation_failed` | Pydantic request validation. `details.errors[]` lists each field. |
| 422 | `invalid_tool_arguments` / `invalid_expression` / `invalid_adapter_yaml` / `invalid_policy_rule` / `dag_cycle` / `invalid_plan` | Semantic validation. |
| 429 | `rate_limited` | Reserved for the Phase 7 limiter. |

---

## 2. Public routes (no credentials)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness/readiness. Also mounted at `/health`. |
| GET | `/api/auth/setup-status` | Whether first-run setup is still required. |
| POST | `/api/auth/setup` | First run only: create the owner account and organization. |
| POST | `/api/auth/login` | Exchange email + password for a token pair. |
| POST | `/api/auth/refresh` | Rotate a refresh token into a new pair. |

`POST /api/auth/setup` returns **409 `already_initialised`** once any user exists, so it can never be
used to create a second anonymous account.

---

## 3. Authentication and membership — `/api/auth`, `/api/members`

### 3.1 Models

```jsonc
// TokenPair
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": { "id": "usr_...", "email": "owner@nexus.app", "display_name": "Owner",
            "is_active": true, "is_superuser": true, "locale": "ar", "theme": "dark",
            "last_login_at": "2026-11-27T12:31:56+00:00", "created_at": "2026-11-27T12:31:56+00:00" }
}

// MeResponse
{
  "user": { /* UserOut */ },
  "organization": { "id": "org_...", "name": "Studio", "slug": "studio",
                    "autonomy_level": "3", "created_at": "2026-11-27T12:31:56+00:00" },
  "role": "owner",                       // owner | admin | member | viewer
  "permissions": ["agents:read", "agents:write", "runs:write", "..."]
}
```

### 3.2 Routes

| Method | Path | Auth | Request | Response |
|---|---|---|---|---|
| GET | `/api/auth/setup-status` | public | — | `{"needs_setup": true, "user_count": 0, "organization_count": 0}` |
| POST | `/api/auth/setup` | public | `{email, password(≥10), display_name, organization_name, organization_slug?, locale?}` | **201** `TokenPair` |
| POST | `/api/auth/login` | public | `{email, password}` | **200** `TokenPair` |
| POST | `/api/auth/refresh` | public | `{refresh_token}` | **200** `TokenPair` |
| POST | `/api/auth/logout` | bearer | `{refresh_token?}` | `{ok: true, message}` |
| GET | `/api/auth/me` | bearer | — | `MeResponse` |
| POST | `/api/auth/password` | bearer | `{current_password, new_password(≥10)}` | `{ok, message}` — revokes all refresh tokens |
| GET | `/api/auth/organizations` | bearer | — | `OrganizationOut[]` |
| POST | `/api/auth/organizations/{organization_id}/switch` | bearer | — | `TokenPair` |
| GET | `/api/members` | `members:write` for writes, read for members | — | `MemberOut[]` |
| POST | `/api/members` | `members:write` | `{email, display_name, password, role}` | **201** `MemberOut` |
| PATCH | `/api/members/{user_id}` | `members:write` | `{role}` | `MemberOut` — **409 `last_owner`** when demoting the final owner |
| GET | `/api/members/roles/grants` | bearer | — | `{"owner": ["..."], "admin": ["..."], "member": [...], "viewer": [...]}` |

**Password hashing:** argon2id (`$argon2id$...`) — never returned by any endpoint.
**Lockout:** `NEXUS_MAX_FAILED_LOGINS` (5) failures lock the account for
`NEXUS_LOCKOUT_SECONDS` (300). The failure counter and the lock are committed even though the
request ends in 401.

### 3.3 Example — complete first run

```bash
# 1. Is setup needed?
curl -s http://127.0.0.1:8000/api/auth/setup-status
# {"needs_setup":true,"user_count":0,"organization_count":0}

# 2. Create the owner (once)
curl -s -X POST http://127.0.0.1:8000/api/auth/setup \
  -H 'Content-Type: application/json' \
  -d '{"email":"owner@nexus.app","password":"a-long-password","display_name":"Owner",
       "organization_name":"Studio","locale":"ar"}'

# 3. Use the access token
curl -s http://127.0.0.1:8000/api/auth/me -H "Authorization: Bearer $ACCESS_TOKEN"
```

---

## 4. Agents and versions — `/api/agents`, `/api/conversations`

### 4.1 Models

```jsonc
// AgentCreate / AgentUpdate (AgentUpdate: every field optional + change_note)
{
  "name": "Backend Engineer",
  "slug": "backend-engineer",          // optional, derived from name
  "description": "",
  "role": "backend",
  "goal": "Ship the API",
  "instructions": "Follow docs/SPEC.md",
  "runtime": "native",                  // native | software_team
  "connection_id": null,
  "model_config_json": {},
  "tools": ["calc.evaluate", "time.now"],
  "limits": {"max_steps": 40, "timeout_seconds": 900, "max_tool_calls": 40},
  "autonomy_level": "3",                // optional per-agent override
  "avatar_color": "#6366f1"
}

// AgentOut
{ "id": "agt_...", "slug": "backend-engineer", "name": "Backend Engineer",
  "description": "", "role": "backend", "avatar_color": "#6366f1",
  "is_enabled": true, "is_archived": false, "current_version": 2,
  "runtime": "native", "connection_id": null, "autonomy_level": null,
  "created_at": "...", "updated_at": "..." }

// AgentDetail = AgentOut + { "current_version_detail": AgentVersionOut | null }

// AgentVersionOut (immutable snapshot)
{ "id": "agv_...", "agent_id": "agt_...", "version": 2, "name": "...", "description": "...",
  "role": "backend", "goal": "...", "instructions": "...", "runtime": "native",
  "connection_id": null, "model_config_json": {}, "tools": ["calc.evaluate"],
  "limits": {...}, "permissions": {}, "change_note": "tighten instructions",
  "created_at": "..." }

// AgentVersionDiff
{ "from_version": 1, "to_version": 2,
  "changed_fields": { "instructions": {"from": "old", "to": "new"} } }
```

### 4.2 Routes

| Method | Path | Permission | Request | Response |
|---|---|---|---|---|
| GET | `/api/agents` | `agents:read` | `?include_archived&limit&offset` | `Page[AgentOut]` |
| POST | `/api/agents` | `agents:write` | `AgentCreate` | **201** `AgentOut` (version 1 created) |
| GET | `/api/agents/{agent_id}` | `agents:read` | — | `AgentDetail` |
| PATCH | `/api/agents/{agent_id}` | `agents:write` | `AgentUpdate` | `AgentOut` (version +1, immutable) |
| POST | `/api/agents/{agent_id}/clone` | `agents:write` | `?name=` | **201** `AgentOut` |
| POST | `/api/agents/{agent_id}/enable` | `agents:write` | `?enabled=true\|false` | `AgentOut` |
| DELETE | `/api/agents/{agent_id}` | `agents:write` | — | `{ok, message}` (archives, does not hard-delete) |
| GET | `/api/agents/{agent_id}/versions` | `agents:read` | — | `AgentVersionOut[]` (newest first) |
| GET | `/api/agents/{agent_id}/versions/{version}` | `agents:read` | — | `AgentVersionOut` |
| GET | `/api/agents/{agent_id}/versions/{from_version}/diff/{to_version}` | `agents:read` | — | `AgentVersionDiff` |
| GET | `/api/agents/{agent_id}/tools` | `agents:read` | — | `string[]` (allow-list) |
| POST | `/api/conversations` | `conversations:write` | `{agent_id, title}` | **201** `ConversationOut` |
| GET | `/api/conversations` | `conversations:read` | `?agent_id&limit&offset` | `Page[ConversationOut]` |
| GET | `/api/conversations/{conversation_id}/messages` | `conversations:read` | `?limit` | `MessageOut[]` |
| POST | `/api/conversations/{conversation_id}/messages` | `conversations:write` | `{content, attachments?}` | **201** `MessageOut` (`usage` is `null`) |

**Versioning rule:** saving an agent always appends a new `agent_versions` row; existing rows are
never modified, so a run always references the exact configuration it used.

### 4.3 Example — create and edit an agent

```bash
curl -s -X POST http://127.0.0.1:8000/api/agents \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Backend Engineer","role":"backend","tools":["calc.evaluate"]}'
# 201 {"id":"agt_...","current_version":1,...}

curl -s -X PATCH http://127.0.0.1:8000/api/agents/agt_... \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"instructions":"Now with tests","change_note":"tighten instructions"}'
# 200 {"current_version":2,...}
```

---

## 5. Runs, events, checkpoints and approvals

### 5.1 Models

```jsonc
// RunCreate
{ "agent_id": "agt_...", "directive": "Build the landing page",
  "conversation_id": null,
  "trigger": "manual",              // manual | chat | schedule | file_watch | git_event
  "idempotency_key": "mission-42" } // optional: same key ⇒ same run, no duplicate work

// RunOut
{ "id": "run_...", "agent_id": "agt_...", "agent_version_id": "agv_...",
  "conversation_id": null, "connection_id": null,
  "status": "created",   // created | running | paused | waiting_for_user | completed | failed | cancelled | resume_available
  "trigger": "manual", "directive": "...", "last_sequence": 3,
  "step_count": 0, "tool_call_count": 0, "error": null,
  "started_at": null, "finished_at": null, "created_at": "..." }

// RunDetail = RunOut + {"latest_checkpoint_step": 3 | null, "pending_approvals": 0}

// EventOut — exactly the SPEC §7 envelope
{ "event_id": "evt_...", "event_version": 1, "organization_id": "org_...",
  "run_id": "run_...", "task_id": null, "agent_id": "agt_...",
  "correlation_id": null, "sequence": 1,
  "event_type": "run.created", "timestamp": "2026-11-27T12:31:56+00:00",
  "source_runtime": "native", "payload": {} }

// CheckpointOut
{ "id": "ckp_...", "run_id": "run_...", "step": 3, "label": "after plan",
  "state": {}, "resumable": true, "created_at": "..." }

// ApprovalOut
{ "id": "apr_...", "kind": "tool_call",   // tool_call | plan | merge
  "status": "pending",                    // pending | approved | rejected | expired
  "run_id": "run_...", "agent_id": "agt_...", "tool_slug": "calc.evaluate",
  "requested_payload": {"arguments": {...}, "reason": "..."},
  "reason": "level 0 asks for every tool call",
  "decided_by": null, "decided_at": null, "decision_note": null, "created_at": "..." }
```

**Event types** (the only values accepted; anything else is a `422 unknown_event_type`):
`run.created|started|paused|resumed|completed|failed|cancelled`, `agent.started|message|stream|code|delegated|waiting|completed|failed`,
`plan.proposed|approved|rejected`, `task.created|assigned|started|completed|failed`,
`tool.execution.started|completed|failed`, `approval.requested|approved|rejected`,
`pr.opened|reviewed|merged|closed`, `checkpoint.created`, `artifact.created`, `memory.updated`,
`connection.state_changed`, `browser.connected|disconnected|session.expired|waiting_for_user|resumed`,
`provider.response.received`, `system.health`, `emergency_stop.engaged|cleared`.

### 5.2 Routes

| Method | Path | Permission | Request | Response |
|---|---|---|---|---|
| POST | `/api/runs` | `runs:write` | `RunCreate` | **201** `RunOut` (409 `emergency_stop_engaged` when the kill switch is on) |
| GET | `/api/runs` | `runs:read` | `?status&agent_id&limit&offset` | `Page[RunOut]` |
| GET | `/api/runs/{run_id}` | `runs:read` | — | `RunDetail` |
| POST | `/api/runs/{run_id}/start` | `runs:write` | — | `RunOut` (`running`) |
| POST | `/api/runs/{run_id}/pause` | `runs:write` | — | `RunOut` (`paused`) |
| POST | `/api/runs/{run_id}/resume` | `runs:write` | — | `RunOut` (`running`) |
| POST | `/api/runs/{run_id}/cancel` | `runs:cancel` | — | `RunOut` (`cancelled`) |
| POST | `/api/runs/{run_id}/complete` | `runs:write` | — | `RunOut` (`completed`) |
| POST | `/api/runs/{run_id}/checkpoints` | `runs:write` | `?step&label` + `state` body | **201** `CheckpointOut` |
| GET | `/api/runs/{run_id}/events` | `events:read` | `?after_sequence&limit` | `EventOut[]` |
| GET | `/api/events` | `events:read` | `?run_id&after_sequence&event_type&limit` | `EventOut[]` |
| GET | `/api/approvals` | `approvals:read` | `?status&run_id&limit&offset` | `Page[ApprovalOut]` |
| POST | `/api/approvals/{approval_id}/decide` | `approvals:write` | `{approve: bool, note}` | `ApprovalOut` (decided twice ⇒ 409) |

**Legal run transitions:** `created → running|paused|failed|cancelled`, `running → paused|waiting_for_user|completed|failed|cancelled`,
`paused → running|cancelled|failed`, `waiting_for_user → running|cancelled|failed`,
`resume_available → running|cancelled`, `failed → resume_available`. Anything else is **409 `illegal_transition`**.

**Event ordering:** `sequence` is monotonic per run and is the client's resume cursor. Events are
written in the same transaction as the state change; `after_sequence=N` replays everything after `N`.

### 5.3 Example — a full run

```bash
RUN=$(curl -s -X POST http://127.0.0.1:8000/api/runs \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"agent_id":"agt_...","directive":"Build the landing page","idempotency_key":"mission-42"}')
# 201 {"id":"run_...","status":"created",...}

curl -s -X POST http://127.0.0.1:8000/api/runs/run_.../start   -H "Authorization: Bearer $ACCESS_TOKEN"
curl -s -X POST "http://127.0.0.1:8000/api/runs/run_.../checkpoints?step=3&label=after%20plan" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' -d '{"state":{"plan":"ok"}}'
curl -s -X POST http://127.0.0.1:8000/api/runs/run_.../complete -H "Authorization: Bearer $ACCESS_TOKEN"

curl -s "http://127.0.0.1:8000/api/runs/run_.../events?after_sequence=2" -H "Authorization: Bearer $ACCESS_TOKEN"
# [{"event_type":"checkpoint.created",...},{"event_type":"run.completed",...}]
```

---

## 6. Tools — the Tool Gateway

### 6.1 Models

```jsonc
// ToolOut
{ "id": "tol_...", "slug": "calc.evaluate", "display_name": "Calculator",
  "description": "...", "input_schema": {"type":"object","properties":{...},"required":["expression"]},
  "requires_approval": false, "enabled": true, "category": "utility" }

// ToolInvokeRequest
{ "tool_slug": "calc.evaluate", "arguments": {"expression": "2+2"}, "run_id": null, "agent_id": null }

// ToolInvokeResult
{ "invocation_id": "tcl_...", "tool_slug": "calc.evaluate",
  "decision": "allow",              // allow | ask | deny
  "outcome": "success",             // success | awaiting_approval | denied | error
  "result": {"value": 4}, "error": null, "approval_id": null, "duration_ms": 3 }
```

### 6.2 Routes

| Method | Path | Permission | Request | Response |
|---|---|---|---|---|
| GET | `/api/tools` | `tools:read` | — | `ToolOut[]` |
| POST | `/api/tools/sync-builtin` | `tools:write` | — | `ToolOut[]` (idempotent registration) |
| POST | `/api/tools/invoke` | `tools:invoke` | `ToolInvokeRequest` | `ToolInvokeResult` |

### 6.3 Gateway behaviour (every call)

1. The tool must exist and be enabled — otherwise `422 tool_disabled` / `404`.
2. If `agent_id` is supplied, the tool must be in the agent's current-version allow-list — otherwise `403 tool_not_allowed`.
3. `arguments` are validated against the tool's JSON Schema — otherwise `422 invalid_tool_arguments`.
4. The action policy decides `allow`, `ask` or `deny` (first matching rule wins). `ask` creates an `Approval` (`outcome: "awaiting_approval"`, `approval_id` set) and emits `approval.requested`.
5. Every call writes a `tool_invocations` row, an audit row and a `tool.execution.*` event — including denials.

**Built-in tools:** `calc.evaluate` (arithmetic over a restricted alphabet — no names, no calls),
`time.now`, `knowledge.search` (honestly returns `{"configured": false}` until Phase 6), and
`http.get` (host allow-list; returns `{"status":"not_fetched"}` in this slice rather than pretending
to fetch).

### 6.4 Example

```bash
curl -s -X POST http://127.0.0.1:8000/api/tools/invoke \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"tool_slug":"calc.evaluate","arguments":{"expression":"(2 + 3) * 4"}}'
# 200 {"invocation_id":"tcl_...","decision":"allow","outcome":"success","result":{"value":20},...}
```

---

## 7. Connections, credentials, devices and adapters

### 7.1 Models

```jsonc
// CapabilityFlags — honest statuses only
{ "streaming": "supported", "native_tool_calling": "unsupported",
  "structured_output": "partial", "multimodal_input": "partial",
  "usage_reporting": "unsupported", "agent_mode": "supported",
  "max_concurrency": 1, "max_prompt_characters": 120000 }

// ConnectionCreate
{ "name": "Mock tab", "provider_slug": "mock", "kind": "browser_session",
  "model": null, "base_url": null, "credential_id": null, "options": {} }

// ConnectionOut
{ "id": "conn_...", "name": "Mock tab", "kind": "browser_session",
  "status": "disabled",              // disabled | enabled | error
  "provider_slug": "mock", "model": null, "base_url": null,
  "capabilities": { /* CapabilityFlags */ }, "terms_acknowledged": false,
  "created_at": "..." }

// BrowserSessionOut (a tab)
{ "id": "bsess_...", "profile_id": "prf_...", "provider_slug": "mock",
  "state": "CONNECTED",              // DISCONNECTED | PAIRING_REQUIRED | CONNECTING | CONNECTED |
                                     // AUTHENTICATED | READY | BUSY | WAITING_FOR_USER |
                                     // RATE_LIMITED | SESSION_EXPIRED | PROVIDER_UNAVAILABLE | ERROR
  "agent_page_state": null,          // ready | generating | idle | keep_working_visible |
                                     // tool_call_limit | pr_ready | needs_human | offline
  "url": "https://mock.example/chat", "title": null,
  "queue_depth": 0, "last_error": null, "granted_agent_id": null }

// AdapterOut
{ "id": "adp_...", "provider_slug": "mock", "version": 2,
  "yaml_body": "id: mock\nversion: 1\n...", "is_active": true,
  "notes": null, "created_at": "..." }

// SelectorTestResult
{ "valid": false, "missing": ["div#reply"],
  "checks": [{"selector": "textarea#prompt", "required": true}, ...],
  "errors": ["required selector not found: div#reply"] }
```

### 7.2 Routes

| Method | Path | Permission | Request | Response |
|---|---|---|---|---|
| GET | `/api/providers` | `connections:read` | — | `ProviderOut[]` |
| POST | `/api/providers/sync-defaults` | `connections:write` | — | `ProviderOut[]` |
| GET | `/api/credentials` | `connections:read` | — | `CredentialOut[]` (never a secret) |
| POST | `/api/credentials` | `connections:write` | `{name, kind, value}` | **201** `CredentialOut` |
| DELETE | `/api/credentials/{credential_id}` | `connections:write` | — | `{ok, message}` |
| GET | `/api/connections` | `connections:read` | — | `ConnectionOut[]` |
| POST | `/api/connections` | `connections:write` | `ConnectionCreate` | **201** `ConnectionOut` |
| PATCH | `/api/connections/{connection_id}` | `connections:write` | `{name?, status?, model?, base_url?, options?}` | `ConnectionOut` |
| POST | `/api/connections/{connection_id}/terms-acknowledgement` | `connections:write` | — | `TermsAckOut` |
| GET | `/api/devices` | `connections:read` | — | `[{id,label,userscript_version,revoked,last_seen_at,created_at}]` |
| POST | `/api/devices/pair` | `bridges:write` | `{label, userscript_version}` | **201** `{device_id, credential, expires_in}` |
| POST | `/api/devices/{device_id}/revoke` | `bridges:write` | — | `{ok, message}` |
| POST | `/api/devices/{device_id}/tabs` | `tabs:write` | `?provider_slug&url&title` | **201** `BrowserSessionOut` |
| GET | `/api/browser-sessions` | `connections:read` | — | `BrowserSessionOut[]` |
| PATCH | `/api/browser-sessions/{tab_id}` | `tabs:write` | `{state?, agent_page_state?, url?, title?, last_error?}` | `BrowserSessionOut` |
| POST | `/api/browser-sessions/{tab_id}/grant` | `tabs:write` | `{agent_id}` | `BrowserSessionOut` |
| GET | `/api/adapters` | `connections:read` | `?provider_slug` | `AdapterOut[]` |
| POST | `/api/adapters` | `adapters:write` | `{provider_slug, yaml_body, notes?}` | **201** `AdapterOut` (version auto-increments) |
| POST | `/api/adapters/selector-test` | `adapters:write` | `{yaml_body}` | `SelectorTestResult` |
| POST | `/api/adapters/{adapter_id}/rollback` | `adapters:write` | — | `AdapterOut` |
| GET | `/api/adapters/active/{provider_slug}` | `connections:read` | — | `AdapterOut` |

### 7.3 Security rules enforced by these routes

- A browser connection **cannot be enabled** before its terms notice is acknowledged — `409 terms_not_acknowledged`.
- A credential value is either `env:VAR_NAME` (kept as a reference) or encrypted with Fernet before storage; `ciphertext` never appears in a response and a raw key can never be persisted through `validate_credential_ref`.
- A pairing credential is returned **once**; only its SHA-256 hash is stored. Revoking a device rotates the hash, disconnects its tabs and takes effect immediately.
- The API provider (`openai_compatible`) ships **disabled**; creating a connection against it returns `409 provider_disabled`.
- `selector-test` never claims a selector passed without a page snapshot: it returns `errors: ["live page not checked: ..."]`.

### 7.4 Example

```bash
curl -s -X POST http://127.0.0.1:8000/api/credentials \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"OpenAI key","kind":"api_key","value":"env:OPENAI_API_KEY"}'
# 201 {"id":"cred_...","name":"OpenAI key","kind":"api_key","credential_ref":"env:OPENAI_API_KEY",...}
```

---

## 8. Missions, tasks, pull requests and reviews

### 8.1 Models

```jsonc
// MissionCreate
{ "title": "Ship the landing page", "directive": "Build and deploy the marketing page",
  "team_id": null,
  "acceptance_criteria": ["page renders in AR and EN"],
  "assumptions": ["brand colours already approved"],
  "tasks": [
    {"key": "api", "title": "Build the API", "specialty": "backend"},
    {"key": "ui", "title": "Build the UI", "specialty": "frontend",
     "depends_on": ["api"], "contract": "docs/API.md"}
  ] }

// MissionOut
{ "id": "msn_...", "title": "...", "directive": "...", "status": "planned", "team_id": null,
  "assumptions": [...], "acceptance_criteria": [...], "plan": {"tasks": [...], "edges": [...]},
  "plan_validation": {"valid": true, "task_count": 2, "edge_count": 1, "warnings": []},
  "replan_budget": 2, "replans_used": 0, "started_at": null, "finished_at": null, "created_at": "..." }

// TaskOut
{ "id": "tsk_...", "mission_id": "msn_...", "title": "Build the API", "description": "",
  "specialty": "backend", "status": "pending", "assignee_agent_id": null, "run_id": null,
  "claimed_by": null, "attempt": 0, "max_attempts": 3,
  "branch_name": "aatm/task-api-build-the-api", "is_parked": false, "error": null }

// MissionTimeline — the 8 steps of SPEC §1, computed from real rows
{ "mission_id": "msn_...", "tasks_total": 2, "tasks_done": 0, "pull_requests": 0,
  "elapsed_seconds": null,
  "steps": [
    {"step": 1, "key": "request",       "state": "done",    "label": "Request", "detail": "directive received"},
    {"step": 2, "key": "analyze",       "state": "done",    "label": "Analyze & split", "detail": "2 tasks planned"},
    {"step": 3, "key": "distribute",    "state": "active",  "label": "Distribute", "detail": "waiting for claims"},
    {"step": 4, "key": "execute",       "state": "pending", "label": "Execute", "detail": "not started"},
    {"step": 5, "key": "collect",       "state": "pending", "label": "Collect", "detail": "awaiting tasks"},
    {"step": 6, "key": "pull_request",  "state": "pending", "label": "Pull request", "detail": "no pull request yet"},
    {"step": 7, "key": "review_merge",  "state": "pending", "label": "Review & merge", "detail": "no review yet"},
    {"step": 8, "key": "completed",     "state": "pending", "label": "Completed", "detail": "mission in progress"}
  ] }

// PullRequestCreate
{ "mission_id": null, "task_id": null, "repository": "oldman-088/multi-agent-project",
  "number": 12, "url": "https://github.com/...", "title": "[AATM-...] backend slice",
  "branch": "arena/2084fdc8-multi-agent-project", "base_branch": "main", "is_draft": true }

// PullRequestOut
{ "id": "pr_...", "mission_id": null, "task_id": null, "repository": "...", "number": 12,
  "url": "...", "title": "...", "branch": "...", "base_branch": "main",
  "is_draft": true, "status": "open", "checks_status": "pending",
  "merged_at": null, "created_at": "..." }

// ReviewCreate → ReviewOut
{ "verdict": "request_changes", "summary": "...", "reviewer_agent_id": "agt_...", "parse_attempts": 1 }
```

### 8.2 Routes

| Method | Path | Permission | Request | Response |
|---|---|---|---|---|
| GET | `/api/missions` | `missions:read` | `?limit&offset` | `Page[MissionOut]` |
| POST | `/api/missions` | `missions:write` | `MissionCreate` | **201** `MissionOut` (**422 `dag_cycle`** for a cyclic plan) |
| GET | `/api/missions/{mission_id}` | `missions:read` | — | `MissionOut` |
| GET | `/api/missions/{mission_id}/tasks` | `missions:read` | — | `TaskOut[]` |
| GET | `/api/missions/{mission_id}/timeline` | `missions:read` | — | `MissionTimeline` |
| POST | `/api/missions/tasks/{task_id}/claim` | `missions:write` | — | `TaskOut` (**409 `dependencies_unfinished`** / `task_not_claimable`) |
| POST | `/api/missions/tasks/{task_id}/complete` | `missions:write` | `?success&error` | `TaskOut` |
| GET | `/api/pull-requests` | `missions:read` | `?mission_id` | `PullRequestOut[]` |
| POST | `/api/pull-requests` | `missions:write` | `PullRequestCreate` | **201** `PullRequestOut` |
| POST | `/api/pull-requests/{pull_request_id}/reviews` | `missions:write` | `ReviewCreate` | **201** `ReviewOut` |
| POST | `/api/pull-requests/{pull_request_id}/merge` | `missions:write` | `?approval_id` | `PullRequestOut` |

**DAG rules:** duplicate task keys → 422; an edge to an unknown key → 422 `invalid_plan`; a cycle → 422
`dag_cycle`; frontend+backend tasks with no declared `contract` → a warning in
`plan_validation.warnings` (never a silent pass).

**Claim safety:** `claim` locks the row (`SELECT … FOR UPDATE`), re-checks `pending`, verifies every
dependency is `completed`, then sets `running` **and** records `claimed_by`/`claimed_at`, so two
workers can never execute the same task.

**Merge safety:** merging requires a `merge`-kind `Approval` with status `approved` and a human
`decided_by`, plus `checks_status == "success"`. An AI review verdict never counts as an approval.

---

## 9. System, policy, audit and dashboard

| Method | Path | Permission | Request | Response |
|---|---|---|---|---|
| GET | `/api/system/autonomy` | `org:read` | — | `{autonomy_level: "3", emergency_stop_engaged: false, level_names: {...}}` |
| PUT | `/api/system/autonomy` | `system:write` | `{level: "0"\|"1"\|"2"\|"3"}` | `AutonomyOut` |
| GET | `/api/system/action-policy` | `org:read` | `?level` | `PolicyRule[]` |
| PUT | `/api/system/action-policy` | `system:write` | `PolicyRule[]` | `PolicyRule[]` (**422 `invalid_policy_rule`** for a rule with no matcher and no `match_all`) |
| POST | `/api/system/action-policy/evaluate` | `org:read` | `{tool?, path?, host?, command?, agent_id?}` | `{decision, matched_rule, reason}` |
| GET | `/api/system/emergency-stop` | bearer | — | `{engaged, reason}` |
| POST | `/api/system/emergency-stop` | `system:write` | `{engage, reason?}` | `{engaged, reason}` |
| GET \| POST | `/api/kill-switch` | `system:write` | `{engage, reason?}` | `{engaged, reason}` |
| GET | `/api/audit` | `audit:read` | `?action&limit&offset` | `AuditLogOut[]` |
| GET | `/api/system/dashboard` | `org:read` | — | real counts (below) |
| GET | `/api/system/usage` | `org:read` | — | `{connections_reporting_usage: 0, tokens: null, cost: null, runs_considered: N, note}` |
| GET | `/api/system/organizations/{organization_id}` | `org:read` | — | organization settings |
| POST | `/api/system/ping` | bearer | — | `{ok: true, message}` |

```jsonc
// PolicyRule — ordered; the first match wins; a rule needs ≥1 matcher or match_all
{ "decision": "ask",            // allow | ask | deny
  "tool": "git.force_push", "path_glob": null, "host": null,
  "command_pattern": null, "agent_id": null, "match_all": false }

// AuditLogOut
{ "id": "aud_...", "actor_id": "usr_...", "actor_type": "user", "action": "tools.invoke",
  "target_type": "tool", "target_id": "calc.evaluate", "outcome": "success",
  "context": {"decision": "allow"}, "ip_address": "127.0.0.1",
  "request_id": "...", "created_at": "..." }

// GET /api/system/dashboard  (every value is a real count)
{ "agents_total": 1, "agents_enabled": 1, "runs_total": 3, "runs_running": 0,
  "runs_waiting_for_user": 0, "approvals_pending": 0, "missions_total": 1,
  "pull_requests_open": 0, "autonomy_level": "3", "emergency_stop_engaged": false }
```

**Default action policy** (`§13.2`): levels `0`/`1` ask for every call; levels `2`/`3` allow
everything **after** a short `ask` list of irreversible actions that leave the sandbox
(`git.force_push`, `fs.delete_outside_workspace`, `payments.charge`, `messages.send_external`).
When no rule matches, the decision is `ask` — never `allow`.

**Kill switch:** stored in `organizations.settings`, survives restarts, emits
`emergency_stop.engaged`/`cleared`, is audited, and is enforced by `POST /api/runs`,
`/start`, `/resume` (`409 emergency_stop_engaged`). It can never be disabled by an autonomy level.

---

## 10. Permission matrix

| Permission | owner | admin | member | viewer |
|---|:--:|:--:|:--:|:--:|
| `org:read` | ✅ | ✅ | ✅ | ✅ |
| `org:write`, `system:write`, `members:write` | ✅ | ✅ / ❌ / ❌ | ❌ | ❌ |
| `agents:read` | ✅ | ✅ | ✅ | ✅ |
| `agents:write` | ✅ | ✅ | ❌ | ❌ |
| `runs:read`, `events:read`, `conversations:read` | ✅ | ✅ | ✅ | ✅ |
| `runs:write`, `conversations:write` | ✅ | ✅ | ✅ | ❌ |
| `runs:cancel` | ✅ | ✅ | ❌ | ❌ |
| `connections:read`, `tools:read`, `missions:read`, `approvals:read`, `audit:read`, `schedules:read` | ✅ | ✅ | ✅ | ✅ |
| `connections:write`, `bridges:write`, `tabs:write`, `adapters:write`, `tools:write` | ✅ | ✅ | ❌ | ❌ |
| `missions:write`, `approvals:write`, `schedules:write`, `tools:invoke` | ✅ | ✅ | ✅ | ❌ |

---

## 11. Relationship to the specification

| SPEC section | Implemented here |
|---|---|
| §6 Phase 2.1 auth, argon2, RBAC | §3, §10 |
| §6 Phase 2.2 database and migrations | every model in `backend/app/models/`, `backend/alembic/versions/0001_initial_schema.py` |
| §6 Phase 2.5 agents and versioning | §4 |
| §6 Phase 2.7 Tool Registry + Gateway | §6 |
| §4.3 / §7 events, outbox, `sequence` | §5 |
| §1 / §6 Phase 3 missions, DAG, timeline, PRs, reviews | §8 |
| §3.1 / §3.2 terms, pairing, secrets, kill switch | §7, §9 |
| §13 autonomy levels and action policy | §9 |
| §11 OpenAPI | `/openapi.json`, `/docs` |

**Not part of this slice (documented, not faked):** the WebSocket stream (`/ws/...`), the Local
Browser Bridge process, the userscript, the ReAct execution loop, sandboxed execution, memory,
knowledge bases, MCP, and framework adapters. Routes for them appear only when they work
(SPEC §0 working rules).
