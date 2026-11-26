# System Design

Target design from SPEC §4, refined by Phase 0 research. Nothing here is implemented yet.

## 1. Components

```mermaid
flowchart LR
  subgraph Desktop["Electron shell (supervises processes, shows health)"]
    WEB["Web frontend<br/>React 19 + Vite<br/>(also runs standalone)"]
  end

  subgraph Backend["Backend: FastAPI modular monolith"]
    API["REST + WebSocket API"]
    AUTH["Auth / RBAC / orgs"]
    CONN["Connection layer<br/>ModelConnection / AgentModeConnection"]
    TOOLS["Tool Registry + Tool Gateway<br/>(validate, authorize, limit, audit, approvals)"]
    EVT["Event outbox + in-process bus<br/>(Redis optional)"]
    DB[("SQLite WAL (default)<br/>PostgreSQL 16 (option)<br/>app tables + events + LangGraph checkpoints")]
  end

  subgraph Workers["Execution workers"]
    RT["Runtimes: native ReAct,<br/>software-team, LangGraph"]
    SBX["Docker sandbox (Phase 5)"]
  end

  subgraph Local["Owner's machine"]
    BR["Local Browser Bridge<br/>127.0.0.1 only<br/>pairing, session registry, per-tab queue"]
    US["Userscript (Tampermonkey)<br/>in the provider tab"]
    TAB["Provider page<br/>(owner signed in manually)"]
    LV["Live view source<br/>(CDP profile or Focus-tab fallback)"]
  end

  OLL["Ollama / local models"]
  OAI["OpenAI-compatible API<br/>(off by default)"]

  WEB <-->|HTTPS + WS events| API
  API --> AUTH
  API --> EVT
  RT --> CONN
  RT --> TOOLS
  TOOLS --> SBX
  RT --> EVT
  EVT --> DB
  API --> DB
  CONN -->|authenticated local HTTP/WS| BR
  CONN --> OLL
  CONN --> OAI
  BR <-->|WS: hello/pair, config, prompt, command, deltas, state| US
  US -->|visible UI only: type, click, read| TAB
  LV -->|frames / owner input| BR
  BR -->|live view relay| API
```

## 2. Data flow: a browser-session request

```mermaid
sequenceDiagram
  autonumber
  participant RT as Runtime (worker)
  participant C as BrowserSessionConnection
  participant B as Bridge (127.0.0.1)
  participant U as Userscript
  participant P as Provider page
  participant E as Event outbox/bus
  participant UI as Frontend

  RT->>C: generate/stream(request, idempotency_key)
  C->>B: POST /requests (paired backend credential)
  B->>B: validate size ≤120k, enqueue on tab queue (concurrency 1)
  B-->>C: queued(position)
  C->>E: connection.state_changed (queue position)
  E-->>UI: WS event
  B->>U: {type:"prompt", request_id, idempotency_key, text}
  U->>U: check stop selectors (CAPTCHA, login, terms)
  alt human check visible
    U->>B: state WAITING_FOR_USER (reason)
    B-->>C: waiting_for_user
    C->>E: browser.waiting_for_user
    E-->>UI: open Live Browser panel, banner "This agent needs you"
    UI->>B: owner resolves it in the live view, then presses Resume
    B->>U: resumed
  end
  U->>P: type in input, click send (visible UI only)
  loop while generating
    U->>B: delta(text chunk) via MutationObserver
    B-->>C: chunk
    C-->>RT: GenerationChunk
    C->>E: agent.stream (not persisted one by one)
  end
  U->>U: generating indicator gone and text stable ≥ stable_ms
  U->>B: answer(request_id, content)
  B-->>C: normalized response (usage: null)
  C->>E: provider.response.received (ids, lengths, duration only)
  Note over U,B: Reload/reconnect with unknown submit status → UNCERTAIN_SUBMISSION, never auto-resubmit
```

## 3. Data flow: a run (native ReAct runtime)

```mermaid
sequenceDiagram
  autonumber
  participant UI as Frontend
  participant API as Backend API
  participant DB as DB (runs, events, checkpoints)
  participant W as Worker
  participant CN as ModelConnection
  participant G as Tool Gateway

  UI->>API: POST /runs (agent_version_id, input)
  API->>DB: tx{ insert run; insert event run.created }
  API-->>UI: run_id
  W->>DB: claim run (job queue)
  W->>DB: tx{ run.started }
  loop until done or a limit is hit (max steps, timeout, max tool calls)
    W->>CN: generate/stream (native tools or text action protocol)
    CN-->>W: action or final answer
    alt tool call
      W->>G: call(tool, args)
      G->>G: allow-list, JSON-Schema validate, limits, audit
      opt requires_approval
        G->>DB: tx{ approval row; approval.requested }
        DB-->>UI: WS event, approval card in chat
        UI->>API: approve / reject
        API->>DB: tx{ approval.approved | approval.rejected }
      end
      G->>DB: tx{ tool.execution.started / completed / failed }
      W->>W: loop detection (repeated identical action)
    end
    W->>DB: tx{ checkpoint.created (per step) }
  end
  W->>DB: tx{ run.completed | run.failed | run.cancelled }
  DB-->>UI: events over WS; reconnecting clients replay after last event_id
```

## 4. Key invariants

- The bridge binds 127.0.0.1 only. Every WS handshake checks Origin and a paired credential.
- The events table is the authority. Each event is written in the same transaction as its state change, and published only after commit.
- `sequence` is monotonic per run.
- Browser-session usage is always `null`. Bridge logs hold ids, lengths, durations and states only.
- The frontend never owns execution state.
