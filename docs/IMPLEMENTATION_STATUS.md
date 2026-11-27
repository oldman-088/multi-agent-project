# IMPLEMENTATION STATUS

Last updated: 2026-11-27 · Task: `AATM-e7410b2b-c9c7-428b-b8ee-dd062c39afc3` (Worker 1 — Backend).

Status vocabulary: **Complete** = implemented, reachable through the API and covered by passing
tests. **Partial** = implemented with a documented limit. **Not started**.

## Backend slice (this task)

| Feature | Status | Implementation path | Tests | Notes |
|---|---|---|---|---|
| FastAPI app factory, `/api` prefix, JSON error envelope | Complete | `backend/app/main.py`, `backend/app/core/errors.py` | `test_health_is_public_and_reports_database` | All routes under `/api`; `X-Request-Id` on every response. |
| PostgreSQL/SQLite models (34 tables, tenant-scoped) | Complete | `backend/app/models/` | `test_all_required_tables_exist`, `test_tenant_scoped_tables_carry_organization_id` | `organization_id` indexed on every tenant-scoped table. |
| Alembic revision on empty SQLite **and** PostgreSQL | Complete | `backend/alembic/versions/0001_initial_schema.py` | `tests/test_migrations.py` | Verified: upgrade → downgrade → upgrade on both. |
| First-run owner account, argon2, lockout | Complete | `backend/app/services/auth_service.py` | `test_setup_status_then_first_run_setup`, `test_password_is_hashed_with_argon2`, `test_login_locks_out_after_repeated_failures` | Setup is public but refuses once a user exists. |
| JWT access/refresh with rotation + replay detection | Complete | `backend/app/core/security.py`, `auth_service.issue_tokens` | `test_refresh_token_rotates_and_detects_replay` | Refresh tokens stored as SHA-256, revocable. |
| RBAC (owner/admin/member/viewer) in a service layer | Complete | `backend/app/auth/rbac.py`, `auth/dependencies.py` | `test_viewer_cannot_write_but_can_read`, `test_protected_routes_require_authentication[42]` | 401 anonymous, 403 wrong role. |
| Tenant isolation | Complete | `require_auth`, every service filters by `organization_id` | `test_agent_from_another_organization_is_invisible` | Cross-tenant ids return 404, not 403 (no existence leak). |
| Agents + immutable versions + clone/enable/archive | Complete | `backend/app/services/agent_service.py` | `test_agent_create_makes_version_one`, `test_agent_update_appends_immutable_version`, `test_agent_clone_and_enable_toggle` | Versions never mutate. |
| Runs with legal transitions, idempotency, checkpoints, resume | Complete | `backend/app/services/run_service.py` | `test_run_lifecycle_emits_monotonic_events`, `test_run_idempotency_key_prevents_duplicate_work`, `test_checkpoint_and_resume`, `test_illegal_run_transition_is_rejected` | `idempotency_key` returns the original run. |
| Events: outbox write, monotonic sequence, replay cursor | Complete | `backend/app/services/event_service.py` | `test_run_lifecycle_emits_monotonic_events`, `test_unknown_event_type_is_never_stored` | Event-type vocabulary enforced against SPEC §7. |
| Tool Registry + Tool Gateway + JSON Schema + allow-list + audit | Complete | `backend/app/services/tool_service.py` | `test_tool_argument_schema_is_enforced`, `test_agent_tool_allowlist_is_enforced`, `test_tool_invocation_succeeds_and_is_audited` | Every call audited and evented, including denials. |
| Action policy (ordered allow/ask/deny, first match) | Complete | `backend/app/services/policy.py`, `system_service.py` | `test_level_zero_policy_asks_for_every_call`, `test_full_auto_allows_but_keeps_irreversible_actions_on_ask`, `test_action_policy_first_match_wins` | Default when nothing matches: **ask**. |
| Approvals inbox with human-only decisions | Complete | `backend/app/services/approval_service.py` | `test_approval_decide_is_audited_and_final`, `test_viewer_cannot_decide_approvals` | AI reviewers can never approve. |
| Global kill switch (persisted, audited, enforced) | Complete | `backend/app/services/system_service.py`, `/api/kill-switch` | `test_emergency_stop_blocks_new_work_until_cleared`, `test_kill_switch_requires_system_permission` | Survives restarts (stored in `organizations.settings`). |
| Audit log | Complete | `backend/app/services/audit.py` | `test_tool_invocation_succeeds_and_is_audited` | Context is secret-redacted before insertion. |
| Credentials encrypted at rest; `env:` indirection | Complete | `backend/app/core/security.py`, `connection_service.py` | `test_credential_is_encrypted_and_never_returned`, `test_raw_credential_refs_are_rejected` | Fernet; raw keys are refused. |
| Connections, terms acknowledgement, providers off by default | Complete | `backend/app/services/connection_service.py` | `test_browser_connection_requires_terms_acknowledgement`, `test_api_provider_is_disabled_by_default` | Cannot enable a browser connection before acknowledging terms. |
| Browser device pairing + revocation | Complete | `connection_service.py` | `test_device_pairing_returns_credential_once_and_revoke_is_immediate` | Credential returned once; only a hash stored. |
| Browser tabs, state machine, agent grants | Complete | `connection_service.py`, `/api/browser-sessions` | `test_tab_grant_and_waiting_for_user_event`, `test_revoked_device_cannot_register_tabs` | `WAITING_FOR_USER` emits `browser.waiting_for_user`. |
| Adapter YAML validation, versioning, rollback, selector test | Complete | `backend/app/services/adapter_service.py` | `test_adapter_versions_are_validated_and_rollback_works`, `test_selector_test_never_claims_an_unchecked_pass` | Never reports a selector pass without a live snapshot. |
| Missions, task DAG validation, atomic claim | Complete | `backend/app/services/mission_service.py` | `test_mission_creation_validates_the_dag`, `test_mission_with_a_cyclic_dag_is_rejected`, `test_task_claim_respects_dependencies_and_is_atomic` | Cycles rejected; contract warnings surfaced. |
| 8-step mission timeline computed from real rows | Complete | `mission_service.build_timeline` | `test_mission_timeline_has_the_eight_computed_steps` | No stored "progress" field. |
| Pull requests, reviews, human-gated merge | Complete | `mission_service.py`, `/api/pull-requests` | `test_merge_requires_a_human_approval_and_green_checks`, `test_ai_review_verdict_is_validated` | Merge needs an approved `merge` Approval + green checks. |
| Command Center dashboard counts, honest usage | Complete | `backend/app/api/routes/system.py` | `test_dashboard_counts_are_real`, `test_usage_is_null_rather_than_invented` | `tokens`/`cost` are `null`. |
| Shared API contract `docs/API.md` | Complete | `docs/API.md` | `test_audit_schema_matches_spec_contract` | Fails if a route is undocumented. |
| Quality gate `scripts/check.sh` + CI | Complete | `scripts/check.sh`, `.github/workflows/backend.yml` | CI: lint+type, SQLite tests, PostgreSQL 16 tests + migrations | — |

## Not in this slice (owned by later phases — do not fake)

| Feature | Status | Why |
|---|---|---|
| WebSocket event stream `/ws/...` | Not started | Needs the frontend stream consumer (Phase 2 item 8). REST replay with `after_sequence` is available now. |
| Local Browser Bridge process + userscript | Not started | Separate processes (`integrations/`), Phase 1. The backend side (devices, tabs, adapters) is Complete. |
| Native ReAct execution loop | Not started | Phase 2 item 6; requires a connection implementation and a worker. |
| Ollama / OpenAI-compatible adapters | Not started | Providers are registered and hidden/disabled; no network calls are made. |
| Sandboxed execution, memory, knowledge, MCP, schedules runtime | Not started | Phases 5–6. `knowledge.search` honestly returns `not configured`. |
| Frontend (React/Electron) | Not started | Worker 2 frontend slice. |

## Known limitations (evidence based)

1. `http.get` validates the host allow-list but performs **no** outbound request in this slice; it
   returns `{"status": "not_fetched"}`. Reported as Partial rather than faked as Complete.
2. There is no WebSocket endpoint yet; clients poll `/api/events?after_sequence=N`.
3. The PostgreSQL CI job is defined in `.github/workflows/backend.yml`; it has not been observed
   running on GitHub Actions from this environment. The same commands were executed locally against
   a real PostgreSQL 16 server (see `docs/DEVELOPMENT_LOG.md`).
