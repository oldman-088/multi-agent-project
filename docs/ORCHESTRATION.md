# Task Manifest Contract

> **Single shared contract.** This document, at exactly the path
> `docs/ORCHESTRATION.md`, is the **only** task-manifest contract in this
> project. Worker 4's orchestration engine and the execution tasks share this
> one path — the orchestration engine must reference `docs/ORCHESTRATION.md`
> exactly. No second task-manifest contract may exist at any other path.

## 1. Purpose

The task manifest (سجل المهام) is the register the orchestration engine and the
execution tasks exchange task data through. Its data schema is defined **only**
here. The reference reader/validator that implements this schema is
[`orchestrator/manifest.py`](../orchestrator/manifest.py) — the orchestration
engine loads and validates register data with it, so both sides always agree on
the same schema.

## 2. Data schema

A manifest document is a JSON object with exactly one field, `tasks`, whose
value is a list of task records:

```json
{
  "tasks": []
}
```

Each task record has **exactly five fields** — no more, no fewer:

| field | type | required | description |
|---|---|---|---|
| id | string | yes | Unique identifier of the task across the manifest. This project uses the AATM task-id form `AATM-<uuid>`, which also matches the `[AATM-<id>]` pull-request title convention. Dependency entries reference tasks by this value. |
| title | string | yes | Short human-readable summary of what the task delivers. |
| assignee | string | yes | The worker that owns execution of the task — `worker-1` … `worker-5` — or the literal `unassigned` when no worker is designated. |
| status | string | yes | Lifecycle state of the task. One of the allowed status values in section 3. |
| dependencies | array of strings | yes (may be empty) | Ids of tasks that must complete before this task may complete. Every entry must reference an `id` present in the same manifest. |

Minimal valid record:

```json
{
  "id": "AATM-1dbc5f1d-f858-474b-b0cc-28ec3ebee603",
  "title": "Build apps/web: React+Vite+Tailwind shell with ar/en/fa i18n, RTL, command palette",
  "assignee": "worker-2",
  "status": "ready",
  "dependencies": []
}
```

## 3. Allowed status values

| status | meaning |
|---|---|
| ready | Ready for the orchestration engine's next step: a queued task that can be dispatched to an executor, or an executed task whose deliverable (an open pull request) is ready for review and merge. |
| in_progress | An executor is actively working on the task and has not submitted a deliverable yet. |
| blocked | Progress is stopped by an external condition. The engine must not dispatch or advance it until the condition clears. |
| done | The task completed and its deliverable was merged. Terminal. |
| failed | The task terminally failed and will not complete. Terminal. |

Informative mapping onto the orchestration engine's runtime task states
(`pending`, `claimed`, `running`, `succeeded`, `failed`, `cancelled`):
`ready` → `pending`, `in_progress` → `claimed`/`running`, `done` → `succeeded`,
`failed` → `failed`/`cancelled`; `blocked` tasks are not dispatched.

## 4. Validation rules

`orchestrator/manifest.py` enforces all of the following and raises
`ManifestError` with the offending task or field named in the message:

1. The document is an object with exactly the field `tasks`, whose value is a list.
2. Every task record is an object with exactly the five schema fields — unknown
   or missing fields are rejected.
3. `id`, `title` and `assignee` are non-empty strings.
4. `status` is one of the allowed status values (section 3).
5. `dependencies` is a list of non-empty strings, without duplicates, and never
   containing the task's own `id`.
6. Task `id` values are unique across the manifest.
7. Every dependency references an `id` present in the manifest.
8. The dependency graph is acyclic.

Rejected examples (each of these raises `ManifestError`):

```text
{"id": "", ...}                          → id: must not be empty
{"status": "queued", ...}                → status: must be one of ['ready', 'in_progress', 'blocked', 'done', 'failed']
{"dependencies": ["same-id"], "id": "same-id", ...} → task cannot depend on itself
two records with the same id             → duplicate task id
a dependency on an absent id             → unknown task id
a → b → a                                → dependencies form a cycle
```

## 5. Examples — the project's current task register

Snapshot of the register at the time of writing. Task ids and titles come from
the project's execution record (AATM task ids, `[AATM-<id>]` PR titles);
statuses from the actual state of each deliverable (merged → `done`, open pull
request → `ready`, actively executing → `in_progress`); `assignee` names the
worker designated in the record or by the documented team-ownership of the
delivered area, else `unassigned`; dependency lists record only documented
build-on relations (from task descriptions and branch ancestry), so an empty
list means "no documented dependency".

### 5.1 Full register snapshot

```json
{
  "tasks": [
    {
      "id": "AATM-d21b812e-ab42-426e-8356-d8006d550e12",
      "title": "Add Playwright E2E spec journeys + config",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-e7410b2b-c9c7-428b-b8ee-dd062c39afc3",
      "title": "Backend implementation and API contract per docs/SPEC.md",
      "assignee": "worker-1",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-d82212d1-1333-4ea0-b31a-02e92002580d",
      "title": "Add CI workflow for TS + E2E against the local stack",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-9487748c-cb6d-402f-97c0-e5fe61e6bea9",
      "title": "Add browser bridge and AI connection layer",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-732b98ff-2893-48cd-961e-1a7d85b2cb59",
      "title": "i18n coverage tests (ar/en/fa) and axe/RTL accessibility suite",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-c73bfd0e-d9ab-4c88-99d1-ccc1ca367444",
      "title": "Orchestration engine (workflows), CI line, and quality gate",
      "assignee": "worker-4",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-1dbc5f1d-f858-474b-b0cc-28ec3ebee603",
      "title": "Build apps/web: React+Vite+Tailwind shell with ar/en/fa i18n, RTL, command palette",
      "assignee": "worker-2",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-ed0b0d16-e474-4271-93f1-7c3651a0fda1",
      "title": "Docker stack: compose file, service Dockerfiles, deployment docs, static validation tests",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-d899439f-9373-4444-9578-ef1c5f58bb9b",
      "title": "Local runtime environment: compose stack, service images, environment template and deployment guide",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-7a3d63bb-e51c-433f-8a1f-9b7b928fd355",
      "title": "Spec conformance suite: events, RBAC isolation, Tool Gateway policy, kill switch",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-0eecd025-ef28-4f8d-997c-54caec787381",
      "title": "Agents, chat, runs and events REST surface with atomic sequencing",
      "assignee": "worker-1",
      "status": "ready",
      "dependencies": ["AATM-e7410b2b-c9c7-428b-b8ee-dd062c39afc3"]
    },
    {
      "id": "AATM-7b3c02d3-1f07-405d-8c22-7928928552bf",
      "title": "Add E2E user journeys and CI integration",
      "assignee": "unassigned",
      "status": "done",
      "dependencies": []
    },
    {
      "id": "AATM-6223cccd-da38-4ef0-9e0b-b31889ad4ea6",
      "title": "Add agent, run, event and tool approval APIs",
      "assignee": "worker-1",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-dbde89d3-56d3-4e53-8ea4-c7cfa914bc71",
      "title": "Docker environment and local deployment",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-6e8b401c-9af6-4b04-bb86-04a4f0bbfa01",
      "title": "شاشات الدردشة والوكلاء والاتصالات (agents, chat, connections MVP with live streaming, tool approvals, bridge pairing)",
      "assignee": "worker-2",
      "status": "ready",
      "dependencies": ["AATM-1dbc5f1d-f858-474b-b0cc-28ec3ebee603"]
    },
    {
      "id": "AATM-e4103400-a174-4240-8e3f-c5ec37d80cbb",
      "title": "SPEC §9 conformance tests (event sequencing, RBAC, Tool Gateway, emergency stop) + E2E against the local stack",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-ec6f8c95-a66f-4a49-8bc7-4ba34463efe9",
      "title": "Complete Chat and Agents frontend",
      "assignee": "worker-2",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-554a885b-3b16-42fb-bd0b-c69d9097b3b2",
      "title": "تنفيذ سجل المهام الجاهزة والعقد المشترك",
      "assignee": "worker-5",
      "status": "in_progress",
      "dependencies": []
    }
  ]
}
```

### 5.2 Currently ready tasks

All currently ready tasks of the project, with their ids and dependencies —
exactly the `ready` entries of the snapshot above (every ready task appears
here; nothing ready is omitted). The orchestration engine processes these in
dependency order: a task whose dependencies contain a non-`done` task waits.

```json
{
  "tasks": [
    {
      "id": "AATM-d21b812e-ab42-426e-8356-d8006d550e12",
      "title": "Add Playwright E2E spec journeys + config",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-e7410b2b-c9c7-428b-b8ee-dd062c39afc3",
      "title": "Backend implementation and API contract per docs/SPEC.md",
      "assignee": "worker-1",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-d82212d1-1333-4ea0-b31a-02e92002580d",
      "title": "Add CI workflow for TS + E2E against the local stack",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-9487748c-cb6d-402f-97c0-e5fe61e6bea9",
      "title": "Add browser bridge and AI connection layer",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-732b98ff-2893-48cd-961e-1a7d85b2cb59",
      "title": "i18n coverage tests (ar/en/fa) and axe/RTL accessibility suite",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-c73bfd0e-d9ab-4c88-99d1-ccc1ca367444",
      "title": "Orchestration engine (workflows), CI line, and quality gate",
      "assignee": "worker-4",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-1dbc5f1d-f858-474b-b0cc-28ec3ebee603",
      "title": "Build apps/web: React+Vite+Tailwind shell with ar/en/fa i18n, RTL, command palette",
      "assignee": "worker-2",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-ed0b0d16-e474-4271-93f1-7c3651a0fda1",
      "title": "Docker stack: compose file, service Dockerfiles, deployment docs, static validation tests",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-d899439f-9373-4444-9578-ef1c5f58bb9b",
      "title": "Local runtime environment: compose stack, service images, environment template and deployment guide",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-7a3d63bb-e51c-433f-8a1f-9b7b928fd355",
      "title": "Spec conformance suite: events, RBAC isolation, Tool Gateway policy, kill switch",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-0eecd025-ef28-4f8d-997c-54caec787381",
      "title": "Agents, chat, runs and events REST surface with atomic sequencing",
      "assignee": "worker-1",
      "status": "ready",
      "dependencies": ["AATM-e7410b2b-c9c7-428b-b8ee-dd062c39afc3"]
    },
    {
      "id": "AATM-6223cccd-da38-4ef0-9e0b-b31889ad4ea6",
      "title": "Add agent, run, event and tool approval APIs",
      "assignee": "worker-1",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-dbde89d3-56d3-4e53-8ea4-c7cfa914bc71",
      "title": "Docker environment and local deployment",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-6e8b401c-9af6-4b04-bb86-04a4f0bbfa01",
      "title": "شاشات الدردشة والوكلاء والاتصالات (agents, chat, connections MVP with live streaming, tool approvals, bridge pairing)",
      "assignee": "worker-2",
      "status": "ready",
      "dependencies": ["AATM-1dbc5f1d-f858-474b-b0cc-28ec3ebee603"]
    },
    {
      "id": "AATM-e4103400-a174-4240-8e3f-c5ec37d80cbb",
      "title": "SPEC §9 conformance tests (event sequencing, RBAC, Tool Gateway, emergency stop) + E2E against the local stack",
      "assignee": "unassigned",
      "status": "ready",
      "dependencies": []
    },
    {
      "id": "AATM-ec6f8c95-a66f-4a49-8bc7-4ba34463efe9",
      "title": "Complete Chat and Agents frontend",
      "assignee": "worker-2",
      "status": "ready",
      "dependencies": []
    }
  ]
}
```

## 6. Change rules

- This document at `docs/ORCHESTRATION.md` is the single source of truth for the
  task-manifest schema. The orchestration engine must reference exactly this
  path. A second task-manifest contract at any other path is a violation.
- `orchestrator/manifest.py` must stay in lockstep with this document: its
  `CONTRACT_PATH` constant names this file, its `SCHEMA_FIELDS` match section 2
  and its `VALID_STATUSES` match section 3. The test-suite
  (`tests/orchestrator/test_manifest.py`) enforces this lockstep and validates
  every example above with the reference validator.
- Schema changes land in this document first, then in
  `orchestrator/manifest.py`, then in the tests — never in one place alone.
