# TECHNICAL DECISIONS

Format: context, options, decision, consequences. Newest first.

---

## TD-001 Portability of the Alembic revision across SQLite and PostgreSQL

**Context.** SPEC §4.2 requires SQLite (WAL, default) and PostgreSQL 16 behind the same models, and
§9 requires `alembic upgrade head` to pass on an **empty** database of each. Autogenerate emitted
`backend.app.db.base.UTCDateTime(...)` calls (not renderable) and `batch_alter_table` blocks (SQLite
only).

**Options.** (a) Two dialect-specific branches inside one revision; (b) one revision written in plain
ordered SQL; (c) separate revision chains per backend.

**Decision.** (b). Enums are stored as `VARCHAR` through a `TypeDecorator`; `JSON` becomes `JSONB` on
PostgreSQL via `with_variant`; datetimes are `TIMESTAMP WITH TIME ZONE` everywhere. The revision
carries a flat ordered `STATEMENTS` list plus a reverse `DROP_ORDER`, executed with `op.execute`.

**Consequences.** One head revision, verifiable on both backends, and `alembic downgrade` works on
PostgreSQL without dropping types. A future schema change must keep the same discipline (no native
`ENUM`, no `batch_alter_table`).

---

## TD-002 Event ordering and replay without a WebSocket yet

**Context.** SPEC §4.3 makes `events` authoritative and §7 requires a monotonic `sequence` per run so
a client can resume from the last id. The WebSocket transport is Phase 2 item 8 and is not in this
slice.

**Options.** (a) Store a per-hub counter in Redis; (b) per-run counter persisted on `runs.last_sequence`
and allocated under a row lock; (c) rely on `created_at`.

**Decision.** (b). `append_event` locks the run row, increments `last_sequence`, and writes the event in
the same transaction as the state change (outbox pattern). Replay is
`GET /api/events?after_sequence=N`.

**Consequences.** Ordering is exact and portable; the WebSocket layer added later only needs to read
`after_sequence` from clients.

---

## TD-003 The default action policy is a deny/ask-safe ordered list

**Context.** SPEC §13.2: ordered `allow | ask | deny` rules, first match wins, and full auto allows
everything **inside the sandbox** while irreversible actions that leave it still ask.

**Options.** (a) An unconditional catch-all dict stored as the last rule; (b) rules must declare at
least one matcher, plus an explicit `match_all` flag for a deliberate catch-all; (c) implicit "allow"
when nothing matches.

**Decision.** (b), and the default when nothing matches is **ask** (never allow). The built-in policy
puts the four irreversible `ask` rules first and the `match_all` catch-all last.

**Consequences.** A malformed policy cannot silently grant permissions (`422 invalid_policy_rule`), and
force-push/payments/deleting outside the workspace always ask even at level 3.

---

## TD-004 Session/engine wiring through `app.state`

**Context.** Tests need to swap the database without monkeypatching module globals, and each
`create_app(settings)` call must be fully isolated from the cached environment settings.

**Options.** (a) Module-level global engine; (b) `app.state.session_factory` read by a dependency;
(c) FastAPI sub-application DI container.

**Decision.** (b) plus `app.dependency_overrides[get_settings] = lambda: settings` inside `create_app`.

**Consequences.** A test builds one app, points `state.engine`/`state.session_factory` at its own
engine, and gets full isolation. No production code path depends on a mutable global.

---

## TD-005 Credential handling

**Context.** SPEC §3.2/§3.3: encrypt secrets at rest, never log them, use `env:VAR_NAME` indirection.

**Options.** (a) Store raw values and rely on the DB being local; (b) Fernet-encrypt raw values and
keep `env:` refs as references; (c) only allow `env:` refs.

**Decision.** (b). `validate_credential_ref` accepts only `env:VAR_NAME` or an encrypted value; a raw
key is rejected before it can be persisted. Device credentials are hashed (SHA-256), returned exactly
once, and rotated on revoke.

**Consequences.** The database alone is not enough to recover a secret, and no secret can appear in a
response or an audit row (the audit writer redacts again on write).

---

## TD-006 Honest placeholders instead of fake features

**Context.** SPEC §0/§3.3 forbid placeholder features and invented metrics.

**Decision.** `knowledge.search` returns `{"configured": false}`; `http.get` enforces its host
allow-list and returns `{"status": "not_fetched"}`; `GET /api/system/usage` returns `tokens: null` and
`cost: null`; `selector-test` reports "live page not checked" when no page snapshot is supplied.
All are recorded as Partial in `IMPLEMENTATION_STATUS.md`.

---

## TD-007 Atomic counter allocation for per-run event and per-chat message sequences

**Context.** SPEC §7 requires `sequence` to be monotonic per run, and the cursor must never repeat an
event. The inherited implementation read `runs.last_sequence` (or `MAX(messages.sequence)`) and then
wrote the next value. Under two concurrent requests both read the same number; the event insert then
failed the `uq_events_run_sequence` constraint and surfaced as an opaque 500, and two chat messages
could share a sequence, making client ordering ambiguous.

**Options.** (a) `SELECT … FOR UPDATE` on the parent row — portable, but it holds a row lock across
the whole request and still needs a retry path; (b) allocate with one `UPDATE … RETURNING` on the
parent counter and retry the child insert under a SAVEPOINT; (c) a database sequence per run — not
portable to SQLite and unbounded in count.

**Decision.** (b). `UPDATE runs SET last_sequence = last_sequence + 1 … RETURNING last_sequence`
is serialised by the row lock, so the value is unique by construction. The child insert runs inside
`session.begin_nested()` and is retried on `IntegrityError`, which also covers the "row does not exist
yet" and "explicit sequence collides" edges. Messages get the same treatment backed by a unique
`(conversation_id, sequence)` index.

**Consequences.** The counter is a high-water mark: a reservation whose request rolls back is
skipped, so sequences are strictly increasing but need not be gap-free — which is exactly what the
`after_sequence` resume cursor needs. Loaded ORM instances are updated with
`set_committed_value`, so serialising a response never triggers a lazy refresh inside the request.

---

## TD-008 Claiming a decision with `UPDATE … WHERE status = :expected`

**Context.** An approval must be decided once (SPEC §1 step 7), and a run must follow the legal
transition table (docs/API.md §5.2). Both were implemented as "read the row, check the state, then
write". Two concurrent requests both observed `pending`/`running` and both succeeded: an approval
could be recorded as approved *and* rejected, and a run could emit both `run.started` and
`run.cancelled`.

**Decision.** The expected current state is part of the `WHERE` clause of the `UPDATE`; the returned
row (or the affected-row count) decides the winner, and zero rows means another request won, so the
loser raises **409** (`approval_not_pending` / `illegal_transition`). The event and audit rows are
therefore written by exactly one request.

**Consequences.** Optimistic concurrency with no extra locks and no lost updates, and the invariants
are testable without threads (`asyncio.gather` against the ASGI app reproduces both races). A
repeated transition that is already in effect stays an idempotent no-op and emits no event.
