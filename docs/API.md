# Frontend API contract (Agents and Chat)

The dashboard uses same-origin requests only. The Vite development proxy forwards `/api` and `/ws` to the backend; production deployments must expose those same relative paths. JSON errors may use either `detail` or `message` for their human-readable text. A successful empty response may use HTTP 204.

## Agents

- `GET /api/agents` → `Agent[]` or `{ "agents": Agent[] }`.
- `POST /api/agents` with `{ "name": string, "goal": string, "runtime": string }` → `Agent` or `{ "agent": Agent }`.
- `GET /api/agents/{agent_id}/versions` → version array or `{ "versions": [...] }`.

An agent has an `id` and `name`, with optional `goal`, `description`, `runtime`, `enabled`, and `version` fields. The agent ID is URL-encoded by the client.

## Conversations and messages

- `GET /api/conversations` → `Conversation[]` or `{ "conversations": Conversation[] }`.
- `POST /api/conversations` with `{}` → `Conversation` or `{ "conversation": Conversation }`.
- `GET /api/conversations/{conversation_id}/messages` → `Message[]` or `{ "messages": Message[] }`.
- `POST /api/conversations/{conversation_id}/messages` with `{ "content": string }` → `Message` or `{ "message": Message }`.

Conversation IDs and agent IDs are URL-encoded. A conversation has an `id` and optional `title`, `agent_id`, and `created_at`. A message has an `id`, a `role` (`user`, `assistant`, `system`, or `tool`), `content`, and optionally `run_id`.

## Run events

`GET`/`POST` calls use the authenticated same-origin browser session. Live output is delivered over `ws(s)://<same-origin>/ws/runs/{run_id}`. Each WebSocket frame is one JSON event with an `event_type`; stream events may provide text as `content`, `message`, or `data.content`. `run.completed`, `run.failed`, and `run.cancelled` terminate the live stream. The client never falls back to a hard-coded host.
