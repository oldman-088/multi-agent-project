# Browser Bridge Protocol

Status: **implemented in this slice** for the bridge side and the backend client. The userscript
(`integrations/userscript/`) and the mock provider (`integrations/mock-provider/`) are **not
implemented yet**. Sections marked *Not implemented* are part of the design, not of the code.

Source of truth in code: `integrations/browser-bridge/src/protocol.py`. Keep it in sync with this file.

## 1. Components and trust boundaries

```
Backend (apps/backend)                 Local Browser Bridge (127.0.0.1 only)            Userscript (browser tab)
BrowserSessionConnection ──HTTP+bearer──► /api/...                                     
                                          /ws/userscript ◄──WebSocket, Origin-checked──── userscript in the owner's tab
```

- The bridge binds **127.0.0.1 only**. `main()` has no host option. There is no unauthenticated
  browser-control endpoint. `/health` returns only status and protocol version.
- The **HTTP API** is for the backend. It requires `Authorization: Bearer <BRIDGE_API_TOKEN>`. The
  token comes from an environment variable, is at least 32 characters, and is compared as a SHA-256
  digest in constant time.
- The **WebSocket** is for the userscript. Every handshake is checked against `BRIDGE_ALLOWED_ORIGINS`
  (exact match after lower-casing and trimming a trailing `/`). Nothing else is accepted before the
  Origin check passes.
- Prompt and response text is never logged by the bridge. Logs contain ids, lengths, states and
  durations only.

## 2. WebSocket: `/ws/userscript`

All frames are JSON text objects with a `type` field. Frames larger than 65 536 characters are
rejected with close code `4400`.

### 2.1 Handshake

1. Client opens the socket with an `Origin` header. The bridge accepts it, then checks the Origin.
   A refused Origin receives close code `4403` before any message is read.
2. Client sends `hello` within **10 seconds**, otherwise close `4408`.
3. The bridge answers with one of: `paired`, `welcome`, `pairing_required`, or a close.

```json
{"type": "hello", "script_version": "1.0.0", "pairing_code": "ABCD2345", "device_name": "laptop"}
{"type": "hello", "script_version": "1.0.0", "device_id": "dev_…", "credential": "…"}
```

| Field | Rule |
|---|---|
| `script_version` | Required. `MAJOR.MINOR.PATCH`. Below `1.0.0` → close `4409` (update link in the UI). |
| `pairing_code` | First-time pairing. One-time, 8 characters, valid 5 minutes. Takes precedence over credentials. |
| `device_id`, `credential` | Reconnect with the device credential issued at pairing. |
| `device_name` | Optional label, at most 64 characters. |

Server responses to `hello`:

```json
{"type": "paired", "device_id": "dev_…", "credential": "…"}      // only once, right after a valid code
{"type": "pairing_required"}                                       // no code and no credential (then close 4404)
{"type": "welcome", "protocol_version": 1, "device_id": "dev_…", "session_state": "AUTHENTICATED"}
```

The credential is shown **once**. The bridge stores only its SHA-256 digest. The userscript must
store the credential itself (for example in the userscript's own storage). The backend never sees it.

### 2.2 Messages from the userscript (after `welcome`)

| `type` | Fields | Effect |
|---|---|---|
| `heartbeat` | — | Answered with `heartbeat_ack`. Token renewal is **not implemented** (see §7). |
| `tab_state` | `tab_id` (string, ≤64), `state` (§3), `agent_state` (optional string, ≤64) | Creates or updates the tab. The bridge assigns its own internal id (`tab_…`), visible through `GET /api/tabs`. |
| `delta` | `request_id`, `text` (≤4000 characters) | Streaming text delta. Accumulated for polling. Ignored unless the request belongs to this device and is dispatched. |
| `result` | `request_id`, `status` (`completed` or `failed`), `text` (optional, ≤200 000), `error_code` (optional, §6) | Finishes the request. Unknown codes become `PROVIDER_ERROR`. |

A schema violation after `welcome` gets `{"type": "error", "code": "BAD_MESSAGE"}`, and the socket
stays open. An unknown `type` gets `{"type": "error", "code": "UNKNOWN_TYPE"}`. Non-JSON frames
or non-object JSON close the socket with `4400`.

### 2.3 Messages from the bridge to the userscript

| `type` | Fields | Meaning |
|---|---|---|
| `request` | `request_id`, `tab_id` (the client's own tab id), `prompt`, `idempotency_key`, `timeout_ms` | Run this prompt in that tab through the visible UI. |
| `cancel` | `request_id` | Stop the request if it is running. The result, if any, is ignored. |
| `heartbeat_ack` | — | Reply to `heartbeat`. |
| `error` | `code` | Reply to a malformed message. |

A `request` is sent **only** while its tab reports `READY` (§3). The userscript should report
`BUSY` when generation starts and `READY` when it finishes. The bridge also moves a tab from `BUSY`
to `READY` when a `result` arrives.

## 3. Session states

`DISCONNECTED, PAIRING_REQUIRED, CONNECTING, CONNECTED, AUTHENTICATED, READY, BUSY, WAITING_FOR_USER, RATE_LIMITED, SESSION_EXPIRED, PROVIDER_UNAVAILABLE, ERROR`

| State | Set by | Dispatch allowed |
|---|---|---|
| `DISCONNECTED` | bridge, when the socket drops or the device is revoked | no |
| `AUTHENTICATED` / `CONNECTED` / `CONNECTING` / `PAIRING_REQUIRED` | userscript (`tab_state`) | no |
| `READY` | userscript | **yes** |
| `BUSY` | userscript, while generating | no |
| `WAITING_FOR_USER` | userscript, on a verification or login screen | no. Requests wait. Only `cancel` is allowed. |
| `RATE_LIMITED`, `SESSION_EXPIRED`, `PROVIDER_UNAVAILABLE`, `ERROR` | userscript | no |

The agent-page states of §4.4 of the spec (`ready`, `generating`, `keep_working_visible`, …) are
passed through as `agent_state` and are not interpreted by the bridge.

## 4. Requests, queueing and idempotency

- **One in-flight request per tab.** Requests for the same tab queue behind a per-tab lock.
  `queue_position` is the number of requests already pending on that tab when the request was
  accepted. Parallelism comes from more tabs, not from overlapping requests in one tab.
- **Idempotency.** Each request carries an `idempotency_key` (1–128 characters). Within a tab, a
  repeated key returns the original request and never submits the prompt again.
- **Uncertain submission.** If the socket drops while a request is dispatched, that request fails
  with `UNCERTAIN_SUBMISSION`. The bridge never resubmits automatically. The owner decides.
- **Timeouts.** A request that has not finished within `timeout_s` (default 120, maximum 600) fails.
  If it had been dispatched, the bridge sends `cancel` and reports `GENERATION_TIMEOUT`. If it was
  still queued, the code is `TIMEOUT`.
- **Cancellation.** A queued request is removed and never reaches the page. A dispatched request
  receives `cancel` and is reported as `cancelled`.
- **Revocation.** Queued requests of a revoked device fail with `DEVICE_OFFLINE`. Dispatched ones
  fail with `UNCERTAIN_SUBMISSION`.
- **Ownership.** A `delta` or `result` is accepted only from the device that owns the request.
  Anything else is ignored.

## 5. Close codes

| Code | Name | When |
|---|---|---|
| 4400 | `BAD_MESSAGE` | Not JSON, not an object, too large, or invalid `hello`/frame. |
| 4401 | `BAD_CREDENTIAL` | Known device, wrong credential. |
| 4402 | `BAD_PAIRING_CODE` | Unknown, expired, or already used pairing code. |
| 4403 | `ORIGIN_REFUSED` | Origin missing or not in `BRIDGE_ALLOWED_ORIGINS`. |
| 4404 | `NOT_REGISTERED` | Unknown device, or no credential and no code. |
| 4408 | `HELLO_TIMEOUT` | No `hello` within 10 s. |
| 4409 | `SCRIPT_TOO_OLD` | `script_version` below `1.0.0`. |
| 4410 | `REVOKED` | Device revoked. Sent to a live socket on revocation, and on reconnect. |
| 4411 | `REPLACED` | The same device connected again. The older socket is closed. |

Standard close codes (e.g. 1000, 1001) are used for ordinary disconnects.

## 6. Error codes (request `error_code`)

`SELECTOR_NOT_FOUND`, `SEND_FAILED`, `GENERATION_TIMEOUT`, `SESSION_EXPIRED`, `RATE_LIMITED`,
`USER_ACTION_REQUIRED`, `TOOL_CALL_LIMIT`, `UNCERTAIN_SUBMISSION`, `CANCELLED`, `TIMEOUT`,
`DEVICE_OFFLINE`, `PROVIDER_ERROR`.

Codes sent by the backend client only (not by the bridge): `BRIDGE_UNREACHABLE`, `BRIDGE_AUTH`,
`BRIDGE_ERROR`, `BRIDGE_NOT_CONFIGURED`, `TAB_NOT_FOUND`, `PROMPT_TOO_LONG`.

## 7. Local HTTP API (for the backend)

All routes except `/health` need `Authorization: Bearer <BRIDGE_API_TOKEN>`.
Missing or malformed header → `401`. Wrong token → `403`. No token configured → `503`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/health` | — | `{"status": "ok", "protocol_version": 1}` (public) |
| POST | `/api/pairing-codes` | — | `{"code", "expires_in_s"}`. Shown once. |
| GET | `/api/devices` | — | `[{"device_id", "name", "revoked", "connected"}]` |
| POST | `/api/devices/{device_id}/revoke` | — | `{"revoked": true}`. Closes the live socket with `4410`. `404` if unknown. |
| GET | `/api/tabs` | — | `[{"tab_id", "device_id", "state", "agent_state", "pending"}]` |
| POST | `/api/tabs/{tab_id}/requests` | `{"prompt", "idempotency_key", "timeout_s"}` | `202` with `RequestOut` (returns at once) |
| GET | `/api/tabs/{tab_id}/requests/{request_id}` | — | `RequestOut`. Poll until `status` is terminal. |
| POST | `/api/tabs/{tab_id}/requests/{request_id}/cancel` | — | `RequestOut` |

`RequestOut` = `{"request_id", "status", "text", "error_code", "queue_position"}`, where `status` is
`queued | dispatched | completed | failed | cancelled`. Terminal values: `completed`, `failed`,
`cancelled`.

Validation: `prompt` 1–20 000 characters, `idempotency_key` 1–128, `timeout_s` > 0 and ≤ 600.
Violations return `422`. Unknown tab or request returns `404`.

**Usage is never reported.** Browser-session responses have no usage field.

## 8. Backend connection

`apps/backend/app/connections/browser_session.py` implements `ModelConnection` on top of §7.
`generate()` submits, then polls every 0.25 s until a terminal status or until
`timeout_s + 10 s` has passed. `stream()` raises `UnsupportedOperation`. Capabilities:
`streaming`, `native_tool_calling`, `usage_reporting`, `agent_mode` are `unsupported`;
`max_concurrency` is 1; `max_prompt_characters` is 20 000.

Configuration (environment only): `BROWSER_BRIDGE_URL`, `BROWSER_BRIDGE_API_TOKEN` (≥ 32 characters),
`BROWSER_BRIDGE_TAB_ID`. The bridge's own settings: `BRIDGE_API_TOKEN`, `BRIDGE_ALLOWED_ORIGINS`
(comma-separated `http(s)://host:port` values), `BRIDGE_PORT` (default 8765).

## 9. Not implemented yet (design only)

- **Userscript** and its version handshake UI; the bridge only enforces the minimum version.
- **Pairing UI and display**: the code is returned by the local API. Nothing shows it on screen yet.
- **Session token renewal through heartbeat**: heartbeats are acknowledged, but the credential is
  not rotated. Credentials do not expire.
- **Pairing attempt limits**: a code can be guessed by brute force within its 5-minute window
  (8 characters from a 31-character alphabet). A rate limit must be added before real use.
- **Live view and owner input relay** (§6, Phase 1 of the spec).
- **Agent-mode commands** (`new_session`, `submit`, `keep_working`, `stop`, `read_last_reply`,
  `select_repo`, `create_pr`, …) and streaming deltas to the backend.
- **Remote mode** (outbound authenticated connection to a NEXUS server).
- **Persistence**: the pairing store and the request registry are in memory. A bridge restart
  forgets devices, credentials and pending requests.
- **Adapters** (`adapters/<provider>.yaml`) and the `WAITING_FOR_USER` resume flow in the UI.
