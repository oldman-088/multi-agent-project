import { expect, test, type APIRequestContext } from '@playwright/test';

/**
 * NEXUS AGENT OS — SPEC conformance journeys, E2E against the LOCAL stack.
 *
 * Task [AATM-e4103400]: the §9 conformance areas (event sequencing, RBAC,
 * Tool Gateway policy, emergency stop) exercised as user journeys from the
 * API surface of the locally running backend (uvicorn), the same way the
 * frontend will drive it.
 *
 * docs/SPEC.md coverage:
 *   - §7/§4.3  run event documents, strictly monotonic per-run `sequence`,
 *              replay from the last seen sequence;
 *   - §2       bootstrap/login/RBAC roles + organization isolation;
 *   - §3.2/§13.2 Tool Gateway allow/ask/deny + approval hook + audit trail;
 *   - §3.2     global emergency stop (kill switch): cancels active runs
 *              within 2 seconds and blocks new work while engaged.
 *
 * Notes:
 *  - Requires the backend to be running at API_BASE_URL (default
 *    http://127.0.0.1:8000); the suite FAILS if it is not reachable.
 *  - The suite is serial and targets the `chromium` project only: it is an
 *    API-level journey (no browser page is needed) and the emergency stop is
 *    global state, so running it once keeps the journeys deterministic.
 *    The reason for skipping other projects is documented here and in the
 *    PR description (not a silent skip).
 *  - Credentials come from the environment with throwaway test-only
 *    defaults — never real secrets.
 */

// Serialize the whole file: bootstrap/roles/emergency-stop share backend state.
test.describe.configure({ mode: 'serial' });

const API = process.env.API_BASE_URL ?? 'http://127.0.0.1:8000';
const OWNER_EMAIL = process.env.E2E_OWNER_EMAIL ?? 'e2e-owner@example.com';
const OWNER_PASSWORD = process.env.E2E_OWNER_PASSWORD ?? 'e2e-test-only-throwaway-pass';

test.beforeAll(async ({ playwright }) => {
  // Fail fast with a clear message when the local stack is not running.
  const probe = await playwright.request.newContext();
  const health = await probe.get(`${API}/api/health`);
  if (!health.ok()) {
    throw new Error(
      `the local backend is not healthy at ${API}/api/health (got ${health.status()}) — ` +
        'start it with: uvicorn backend.app.main:app --port 8000'
    );
  }
  await probe.dispose();
});

test.beforeEach(() => {
  // API-level journeys run once (chromium project); no browser is exercised.
  // Documented here and in the PR description — not a silent skip.
  test.skip(
    test.info().project.name !== 'chromium',
    'API conformance journeys run once (chromium project only); no browser needed',
  );
});

/** Authenticated request helper. */
async function call(
  context: { request: APIRequestContext },
  method: string,
  path: string,
  body?: unknown,
  token?: string,
): Promise<{ status: number; json: any }> {
  const res = await context.request.fetch(`${API}${path}`, {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...(body !== undefined ? { data: JSON.stringify(body) } : {}),
  });
  let json: any = null;
  try {
    json = await res.json();
  } catch {
    // non-JSON response body is fine
  }
  return { status: res.status(), json };
}

let ownerToken = '';
let ownerUser: any = null;

async function createRun(token: string, overrides: Record<string, unknown> = {}) {
  const res = await call({ request: getSharedRequest() }, 'POST', '/api/runs',
    { goal: 'e2e conformance run', ...overrides }, token);
  expect(res.status, JSON.stringify(res.json)).toBe(201);
  return res.json;
}

/** Worker-scoped shared request context (created lazily; disposed in afterAll). */
let sharedRequest: APIRequestContext | null = null;
function getSharedRequest(): APIRequestContext {
  if (sharedRequest === null) {
    throw new Error('shared request context not initialised');
  }
  return sharedRequest;
}

test.beforeAll(async ({ playwright }) => {
  sharedRequest = await playwright.request.newContext();
  // First-run bootstrap; on an already-bootstrapped database, log in instead.
  const boot = await call({ request: sharedRequest }, 'POST', '/api/auth/bootstrap', {
    email: OWNER_EMAIL,
    password: OWNER_PASSWORD,
  });
  if (boot.status === 409) {
    const login = await call({ request: sharedRequest }, 'POST', '/api/auth/login', {
      email: OWNER_EMAIL,
      password: OWNER_PASSWORD,
    });
    expect(login.status, 'login with the documented E2E owner credentials').toBe(200);
    ownerToken = login.json.access_token;
    ownerUser = login.json.user;
  } else {
    expect(boot.status, 'bootstrap').toBe(200);
    ownerToken = boot.json.access_token;
    ownerUser = boot.json.user;
  }
});

test.afterAll(async () => {
  // Never leave the global kill switch engaged for whoever runs next.
  if (sharedRequest !== null) {
    await call({ request: sharedRequest }, 'POST', '/api/system/emergency-stop/clear', undefined,
      ownerToken);
    await sharedRequest.dispose();
    sharedRequest = null;
  }
});

/* -------------------------------------------------------------------------- */
/* Journey 1 — health + RBAC surface                                          */
/* -------------------------------------------------------------------------- */

test('journey 1: public health, then 401 for every protected route without a token', async ({
  playwright,
}) => {
  const anon = await playwright.request.newContext();
  const health = await call({ request: anon }, 'GET', '/api/health');
  expect(health.status).toBe(200);
  expect(health.json).toMatchObject({ status: 'ok', database: 'ok' });

  const protectedRoutes: Array<[string, string, unknown?]> = [
    ['GET', '/api/auth/me'],
    ['GET', '/api/runs'],
    ['POST', '/api/runs', { goal: 'x' }],
    ['GET', '/api/tools'],
    ['GET', '/api/tool-calls'],
    ['GET', '/api/approvals'],
    ['GET', '/api/events'],
    ['GET', '/api/system/emergency-stop'],
    ['POST', '/api/system/emergency-stop', { reason: 'x' }],
    ['POST', '/api/users', { email: 'x@example.test', password: 'longenough1' }],
  ];
  for (const [method, path, body] of protectedRoutes) {
    const res = await call({ request: anon }, method, path, body);
    expect(res.status, `${method} ${path} without credentials`).toBe(401);
  }
  await anon.dispose();
});

test('journey 1b: the owner session identifies the first-run account', async () => {
  const me = await call({ request: getSharedRequest() }, 'GET', '/api/auth/me', undefined,
    ownerToken);
  expect(me.status).toBe(200);
  expect(me.json.role).toBe('owner');
  expect(me.json.email).toBe(OWNER_EMAIL);
  expect(me.json.organization_id).toBe(ownerUser.organization_id);
});

/* -------------------------------------------------------------------------- */
/* Journey 2 — run lifecycle + event sequencing (§7, §4.3)                    */
/* -------------------------------------------------------------------------- */

test('journey 2: a run emits strictly monotonic §7 events and replays from the last sequence', async () => {
  const run = await createRun(ownerToken, { autonomy_level: 3 });
  const started = await call({ request: getSharedRequest() }, 'POST',
    `/api/runs/${run.id}/start`, undefined, ownerToken);
  expect(started.status).toBe(200);

  for (const expression of ['2+2', '10*10']) {
    const call_ = await call({ request: getSharedRequest() }, 'POST',
      `/api/runs/${run.id}/tool-calls`,
      { tool: 'calculator', arguments: { expression } }, ownerToken);
    expect(call_.status).toBe(201);
    expect(call_.json.status).toBe('completed');
  }
  const completed = await call({ request: getSharedRequest() }, 'POST',
    `/api/runs/${run.id}/complete`, undefined, ownerToken);
  expect(completed.status).toBe(200);

  const all = await call({ request: getSharedRequest() }, 'GET',
    `/api/runs/${run.id}/events`, undefined, ownerToken);
  expect(all.status).toBe(200);
  const events = all.json.events;
  expect(events.length).toBeGreaterThanOrEqual(6);
  expect(events[0].event_type).toBe('run.created');

  // §7 document shape
  const SPEC_FIELDS = ['event_id', 'event_version', 'organization_id', 'run_id', 'task_id',
    'agent_id', 'correlation_id', 'sequence', 'event_type', 'timestamp', 'source_runtime',
    'payload'];
  for (const event of events) {
    for (const field of SPEC_FIELDS) expect(event).toHaveProperty(field);
    expect(event.run_id).toBe(run.id);
    expect(event.timestamp.endsWith('Z')).toBe(true);
  }
  // strictly monotonic sequence per run
  for (let i = 1; i < events.length; i++) {
    expect(events[i].sequence, `events[${i}].sequence`).toBe(events[i - 1].sequence + 1);
  }
  const types = events.map((e: any) => e.event_type);
  expect(types).toContain('run.started');
  expect(types).toContain('tool.execution.started');
  expect(types).toContain('tool.execution.completed');
  expect(types).toContain('run.completed');

  // §4.3 replay from the last seen sequence
  const lastSeen = events[1].sequence;
  const replay = await call({ request: getSharedRequest() }, 'GET',
    `/api/runs/${run.id}/events?after=${lastSeen}`, undefined, ownerToken);
  expect(replay.json.events.map((e: any) => e.sequence))
    .toEqual(events.filter((e: any) => e.sequence > lastSeen).map((e: any) => e.sequence));
  const newest = events[events.length - 1].sequence;
  const empty = await call({ request: getSharedRequest() }, 'GET',
    `/api/runs/${run.id}/events?after=${newest}`, undefined, ownerToken);
  expect(empty.json.events).toEqual([]);
});

/* -------------------------------------------------------------------------- */
/* Journey 3 — RBAC roles and organization isolation (§2)                     */
/* -------------------------------------------------------------------------- */

test('journey 3: viewer is read-only, member cannot administer', async () => {
  const request = getSharedRequest();
  const suffix = Date.now();

  const viewer = await call({ request }, 'POST', '/api/users', {
    email: `viewer-${suffix}@example.test`,
    password: 'viewer-pass-123',
    role: 'viewer',
  }, ownerToken);
  expect(viewer.status).toBe(201);
  const viewerToken = (await call({ request }, 'POST', '/api/auth/login', {
    email: `viewer-${suffix}@example.test`,
    password: 'viewer-pass-123',
  })).json.access_token;

  expect((await call({ request }, 'GET', '/api/runs', undefined, viewerToken)).status).toBe(200);
  expect((await call({ request }, 'POST', '/api/runs', { goal: 'nope' },
    viewerToken)).status).toBe(403);
  expect((await call({ request }, 'POST', '/api/system/emergency-stop', { reason: 'nope' },
    viewerToken)).status).toBe(403);

  const member = await call({ request }, 'POST', '/api/users', {
    email: `member-${suffix}@example.test`,
    password: 'member-pass-123',
    role: 'member',
  }, ownerToken);
  expect(member.status).toBe(201);
  const memberToken = (await call({ request }, 'POST', '/api/auth/login', {
    email: `member-${suffix}@example.test`,
    password: 'member-pass-123',
  })).json.access_token;

  expect((await call({ request }, 'POST', '/api/runs', { goal: 'member run' },
    memberToken)).status).toBe(201);
  expect((await call({ request }, 'POST', '/api/users', {
    email: `member2-${suffix}@example.test`, password: 'member-pass-123',
  }, memberToken)).status).toBe(403);
  expect((await call({ request }, 'POST', '/api/organizations', { name: 'nope' },
    memberToken)).status).toBe(403);
});

test('journey 3b: an organization B member cannot see organization A data', async () => {
  const request = getSharedRequest();
  const suffix = Date.now();

  const orgB = await call({ request }, 'POST', '/api/organizations', { name: 'Org B E2E' },
    ownerToken);
  expect(orgB.status).toBe(201);
  const memberB = await call({ request }, 'POST',
    `/api/organizations/${orgB.json.id}/users`, {
      email: `orgb-${suffix}@example.test`,
      password: 'orgb-pass-1234',
      role: 'member',
    }, ownerToken);
  expect(memberB.status).toBe(201);
  const memberBToken = (await call({ request }, 'POST', '/api/auth/login', {
    email: `orgb-${suffix}@example.test`,
    password: 'orgb-pass-1234',
  })).json.access_token;

  const runA = await createRun(ownerToken);
  expect((await call({ request }, 'GET', '/api/runs', undefined,
    memberBToken)).json).toEqual([]);
  expect((await call({ request }, 'GET', `/api/runs/${runA.id}`, undefined,
    memberBToken)).status).toBe(404);
  expect((await call({ request }, 'GET', `/api/runs/${runA.id}/events`, undefined,
    memberBToken)).status).toBe(404);
  expect((await call({ request }, 'GET', '/api/tool-calls', undefined,
    memberBToken)).json).toEqual([]);
  expect((await call({ request }, 'GET', '/api/approvals', undefined,
    memberBToken)).json).toEqual([]);
});

/* -------------------------------------------------------------------------- */
/* Journey 4 — Tool Gateway policy (§3.2, §13.2)                              */
/* -------------------------------------------------------------------------- */

test('journey 4: unknown tool 404 + audited, schema violation 422 + audited, deny by allow-list', async () => {
  const request = getSharedRequest();
  const run = await createRun(ownerToken, { allowed_tools: ['calculator'] });
  await call({ request }, 'POST', `/api/runs/${run.id}/start`, undefined, ownerToken);

  const unknown = await call({ request }, 'POST', `/api/runs/${run.id}/tool-calls`,
    { tool: 'definitely_not_a_tool', arguments: {} }, ownerToken);
  expect(unknown.status).toBe(404);

  const badArgs = await call({ request }, 'POST', `/api/runs/${run.id}/tool-calls`,
    { tool: 'calculator', arguments: { expression: 5 } }, ownerToken);
  expect(badArgs.status).toBe(422);

  const denied = await call({ request }, 'POST', `/api/runs/${run.id}/tool-calls`,
    { tool: 'current_time', arguments: {} }, ownerToken);
  expect(denied.status).toBe(201);
  expect(denied.json.policy_decision).toBe('deny');
  expect(denied.json.policy_reason).toBe('not_in_run_allow_list');
  expect(denied.json.status).toBe('denied');

  const audit = await call({ request }, 'GET', `/api/tool-calls?run_id=${run.id}`, undefined,
    ownerToken);
  expect(audit.json).toHaveLength(3);
  for (const row of audit.json) {
    expect(['allow', 'ask', 'deny']).toContain(row.policy_decision);
    expect(row.policy_reason).toBeTruthy();
  }
});

test('journey 4b: http_get is denied off the host allow-list and approved on it', async () => {
  const request = getSharedRequest();
  const run = await createRun(ownerToken, { autonomy_level: 1 });
  await call({ request }, 'POST', `/api/runs/${run.id}/start`, undefined, ownerToken);

  const denied = await call({ request }, 'POST', `/api/runs/${run.id}/tool-calls`,
    { tool: 'http_get', arguments: { url: 'http://example.com/not-allowed' } }, ownerToken);
  expect(denied.status).toBe(201);
  expect(denied.json.policy_decision).toBe('deny');
  expect(denied.json.policy_reason).toBe('host_not_in_allowlist');

  // 127.0.0.1 is allow-listed but http_get always requires human approval.
  const ask = await call({ request }, 'POST', `/api/runs/${run.id}/tool-calls`,
    { tool: 'http_get', arguments: { url: `${API}/api/health` } }, ownerToken);
  expect(ask.status).toBe(201);
  expect(ask.json.policy_decision).toBe('ask');
  expect(ask.json.status).toBe('pending_approval');

  const pending = await call({ request }, 'GET',
    `/api/approvals?approval_status=pending&run_id=${run.id}`, undefined, ownerToken);
  expect(pending.json).toHaveLength(1);
  const approvalId = pending.json[0].id;

  const approved = await call({ request }, 'POST',
    `/api/approvals/${approvalId}/approve`, undefined, ownerToken);
  expect(approved.status).toBe(200);

  const audit = await call({ request }, 'GET', `/api/tool-calls?run_id=${run.id}`, undefined,
    ownerToken);
  const approvedCall = audit.json.find((row: any) => row.id === ask.json.id);
  expect(approvedCall.status).toBe('completed');
  expect(approvedCall.result.status_code).toBe(200);
});

/* -------------------------------------------------------------------------- */
/* Journey 5 — emergency stop / kill switch (§3.2)                            */
/* -------------------------------------------------------------------------- */

test('journey 5: the kill switch cancels active runs within 2s and blocks new work until cleared',
  async () => {
    const request = getSharedRequest();
    const run = await createRun(ownerToken, { autonomy_level: 3 });
    await call({ request }, 'POST', `/api/runs/${run.id}/start`, undefined, ownerToken);

    const t0 = Date.now();
    const engage = await call({ request }, 'POST', '/api/system/emergency-stop',
      { reason: 'e2e kill switch' }, ownerToken);
    const elapsed = Date.now() - t0;
    expect(engage.status).toBe(200);
    expect(engage.json.engaged).toBe(true);
    expect(elapsed, 'kill switch must stop everything within 2 seconds').toBeLessThan(2000);

    // The run was cancelled by the switch.
    const cancelled = await call({ request }, 'GET', `/api/runs/${run.id}`, undefined,
      ownerToken);
    expect(cancelled.json.status).toBe('cancelled');
    const events = await call({ request }, 'GET', `/api/runs/${run.id}/events`, undefined,
      ownerToken);
    const cancellations = events.json.events.filter(
      (e: any) => e.event_type === 'run.cancelled'
    );
    expect(cancellations[cancellations.length - 1].payload.reason).toBe(
      'emergency_stop_engaged'
    );

    // No new work while engaged.
    expect((await call({ request }, 'POST', '/api/runs', { goal: 'blocked' },
      ownerToken)).status).toBe(409);

    // The engaged + cleared events are in the org feed with increasing sequences.
    const cleared = await call({ request }, 'POST', '/api/system/emergency-stop/clear',
      undefined, ownerToken);
    expect(cleared.status).toBe(200);

    const feed = await call({ request }, 'GET',
      '/api/events?event_type=emergency_stop.engaged', undefined, ownerToken);
    expect(feed.json.events.length).toBeGreaterThanOrEqual(1);
    expect(feed.json.events.at(-1).payload.reason).toBe('e2e kill switch');

    // Work resumes after clearing.
    const resumed = await createRun(ownerToken);
    expect(resumed.status).toBe('pending');
  });
