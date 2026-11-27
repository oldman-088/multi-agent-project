# SPEC CONFORMANCE — what `tests/test_spec_conformance.py` proves, and what it cannot

Owner: Worker 5 — General Engineer (AATM-7a3d63bb-e51c-433f-8a1f-9b7b928fd355).
Source of truth: [`docs/SPEC.md`](./SPEC.md). Status vocabulary follows SPEC §3.3 / §11:
**Complete** = implemented, reachable and covered by a passing test · **Partial** = implemented
with a documented limit · **Not tested** = no test exists yet (nothing here is silently assumed).

The suite is deliberately **service-free**: it runs the real FastAPI app, the real service layer
and a real SQLite (WAL) database in-process. Only the *connections* of SPEC §4.4 are mocked
(`MockModelConnection`, `MockBrowserSession`); every assertion is made against production code.

## Covered (Complete)

| SPEC | Requirement | Test(s) |
|---|---|---|
| §7 | `sequence` is monotonic **per run**, gapless from 1, never repeated | `test_run_events_are_monotonic_and_contiguous`, `test_each_run_has_its_own_sequence_counter` |
| §7 / §4.3 | The database itself rejects a re-used `(run_id, sequence)` (`uq_events_run_sequence`) | `test_duplicate_sequence_is_rejected_by_the_database` |
| §7 | Reconnect cursor `after_sequence` never repeats or skips | `test_run_events_are_monotonic_and_contiguous`, `test_organization_stream_is_monotonic_and_resumable` |
| §7 | Payloads are secret-redacted before storage | `test_mock_connection_turn_is_persisted_in_order_and_redacted` |
| §6 P2.1 | Authentication: 401 for anonymous callers on 15 representative routes | `test_anonymous_callers_get_401` |
| §6 P2.1 | RBAC: `viewer` reads but cannot write, and the owner can | `test_viewer_reads_but_cannot_write` |
| §6 P2.2 / §3.2 | RBAC tenant isolation: **org A ≠ org B** for agents, runs, run events, org events, audit rows, the tool registry and approvals | `test_organisation_b_cannot_read_organisation_a_resources`, `test_organisation_b_cannot_read_audit_tools_or_decide_approvals` |
| §6 P2.2 / §3.2 | The `X-Organization-Id` override cannot be spoofed | `test_cannot_select_an_organisation_you_do_not_belong_to` |
| §3.2 / §13.2 | Tool Gateway `allow` executes and is audited | `test_policy_allow_executes_the_tool_and_audits_it` |
| §3.2 / §13.2 | Tool Gateway `ask` creates a pending approval and **does not execute** | `test_policy_ask_creates_a_pending_approval_and_does_not_run` |
| §13.2 | Irreversible actions and `requires_approval` tools always ask, even in full-auto | `test_irreversible_and_flagged_tools_always_ask` |
| §13.2 | Tool Gateway `deny` blocks execution and is audited as denied | `test_policy_deny_blocks_execution_and_is_audited` |
| §13.2 | Ordered rules: first match wins | `test_policy_first_match_wins` |
| §6 P2.7 | JSON-Schema argument validation and the per-agent tool allow-list | `test_gateway_enforces_argument_schema_and_agent_allowlist` |
| §3.1 / §3.2 | `http.get` never reaches a host outside the allow-list | `test_gateway_refuses_hosts_outside_the_allowlist` |
| §3.2 | Every allow/ask/deny decision produces exactly one audit row | `test_every_gateway_decision_is_audited` |
| §3.2 / §13.4 | Kill switch blocks new work (run creation **and** start) until cleared | `test_kill_switch_blocks_new_work_until_cleared` |
| §3.2 | Kill switch state survives an app restart (database-backed) | `test_kill_switch_state_survives_a_restart` |
| §3.2 | Kill switch is idempotent and emits one event per transition | `test_kill_switch_is_idempotent_and_emits_one_event_per_transition` |
| §3.2 / §13.2 | Only `system:write` can operate the kill switch | `test_only_system_write_can_operate_the_kill_switch` |
| §9 | Live smoke test against a running server (`NEXUS_BASE_URL`) | `test_live_local_backend_smoke` |

## Not tested here — and why (gaps)

| SPEC | Requirement | Why it is not covered by this suite | Where it is covered today |
|---|---|---|---|
| §7 | **WebSocket** event stream with resume | No WebSocket endpoint exists yet (backend PR reports it as Not started) | REST replay via `/api/runs/{id}/events?after_sequence=N`; asserted here |
| §7 | JSON **Schema** validation of event payloads (`packages/event-schemas`) | The package does not exist in any branch yet; today the event *type* vocabulary is enforced | `tests/test_backend_spec.py::test_unknown_event_type_is_never_stored` |
| §3.2 | Start-to-finish kill-switch latency **≤ 2 s** | Needs a running worker to cancel; there is no execution loop in the backend slice | Kill-switch blocking behaviour is asserted; the 2-second budget is **Partial** |
| §13.3 / §13.4 | `WAITING_FOR_USER` never blocks the mission; fallback chain; notification | Requires the bridge, a worker and the browser fallback chain (Phases 1/3) | Tab state change + `browser.waiting_for_user` event asserted here |
| §13.4 | Profile-pool autoscaling 1 → N tabs, one in-flight request per tab | Requires the browser bridge process | — |
| §13.4 | The bridge never touches cookies / never rotates identity / never touches the verification screen | Requires the bridge and userscript (not started) | — |
| §3.1 | Terms notice on first browser transport enable | Backend terms-acknowledgement flow is covered by the backend suite | `tests/test_backend_spec.py::test_browser_connection_requires_terms_acknowledgement` |
| §2/§9 | PostgreSQL 16 parity | Needs a PostgreSQL server; CI runs the same suite against PostgreSQL | `.github/workflows/backend.yml` → `pytest (PostgreSQL 16)` |
| §8 | GUI / RTL / i18n / axe conformance | Frontend is owned by another worker and is not on `main` yet | — |
| §9 | E2E journeys (Playwright) against the running app | Needs a browser runtime and the frontend | — |

## How to run

```bash
pip install -e ".[test]"          # or: pip install pytest pytest-asyncio httpx
pytest tests/test_spec_conformance.py -q

# Against a worktree that holds backend/ but not this file:
NEXUS_BACKEND_ROOT=/path/to/worktree pytest tests/test_spec_conformance.py -q

# Optional read-only smoke test against a live server:
NEXUS_BASE_URL=http://127.0.0.1:8000 pytest tests/test_spec_conformance.py -q -k live
```

If `backend/` is absent from the checkout, the module **skips with an explicit reason**
(SPEC §9 forbids a silent pass) and runs as soon as the backend PR lands on `main`.
