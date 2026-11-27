import { test, expect } from '@playwright/test';

/**
 * NEXUS AGENT OS — Core user journey E2E integration tests
 *
 * Spec source: docs/SPEC.md (NEXUS AGENT OS Master Execution Prompt, MVP =
 * Phases 1-2). Each journey verifies the full user flow end-to-end: the
 * frontend page AND the backend API together, asserting on both the rendered
 * UI and the JSON API responses.
 *
 * API surface: derived from docs/SPEC.md route conventions (REST under /api,
 * real-time over /ws). docs/API.md does not exist in this repository yet, so
 * every path below is spec-derived. Selectors assume the frontend exposes test
 * hooks (data-testid) and the bilingual (Arabic default / English) labels the
 * spec requires.
 *
 * IMPORTANT GAP: this repository currently ships only docs/SPEC.md — there is
 * no frontend, backend, or running stack. The tests are written to be correct
 * against a fully built stack (frontend http://localhost:3000, backend
 * http://localhost:8000) but cannot be executed end-to-end here. The gap is
 * documented in the pull request description.
 */

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000';
const API_BASE = process.env.API_BASE_URL ?? 'http://localhost:8000';

async function apiJson(request, method: string, path: string, body?: unknown) {
  const res = await request.fetch(`${API_BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  let parsed: unknown = null;
  try {
    parsed = await res.json();
  } catch {
    // non-JSON response
  }
  return { res, ok: res.ok(), status: res.status(), body: parsed };
}

/* -------------------------------------------------------------------------- */
/* Journey 1 — First run: create the owner account                            */
/* -------------------------------------------------------------------------- */

test.describe('Journey 1 — First run: owner account creation', () => {
  test('creates an owner account through the UI and the account is visible in the backend', async ({ page, request }) => {
    await page.goto('/');

    // Frontend: first-run wizard is shown (Arabic default per SPEC §8.2).
    await expect(
      page.getByTestId('first-run-heading')
    ).toBeVisible();

    await page.getByTestId('email-input').fill('owner@example.com');
    await page.getByTestId('password-input').fill('StrongPass123!');
    await page.getByTestId('confirm-password-input').fill('StrongPass123!');
    await page.getByTestId('create-account-button').click();

    // Frontend: redirected to the command center / dashboard.
    await expect(page).toHaveURL(/(^|\/)((dashboard|command-center)\/?)?$/);
    await expect(page.getByTestId('command-center-heading')).toBeVisible();

    // Backend: the account exists and the session is authenticated.
    const { ok, status, body } = await apiJson(request, 'GET', '/api/auth/me');
    expect(ok, `GET /api/auth/me returned ${status}`).toBeTruthy();
    expect((body as any)?.email).toBe('owner@example.com');
    expect((body as any)?.role).toBe('owner');

    const cookies = await page.context().cookies();
    expect(
      cookies.some((c) => /session|token/.test(c.name))
    ).toBeTruthy('an auth session cookie should be set');
  });
});

/* -------------------------------------------------------------------------- */
/* Journey 2 — Connect a browser device (pairing via the Local Browser Bridge)*/
/* -------------------------------------------------------------------------- */

test.describe('Journey 2 — Connect a browser device (pairing)', () => {
  test('pairs a browser device through the Connection Manager and the device shows in the backend', async ({ page, request }) => {
    await page.goto('/connections');

    // Frontend: no devices paired yet.
    await expect(page.getByTestId('connections-heading')).toBeVisible();
    await expect(page.getByTestId('devices-list')).toBeVisible();

    // Start pairing: the bridge issues a one-time pairing code (6-8 chars).
    await page.getByTestId('start-pairing-button').click();
    const pairing = page.getByTestId('pairing-code-display');
    await expect(pairing).toBeVisible();
    const code = await pairing.textContent();
    expect(code?.trim().length).toBeGreaterThanOrEqual(6);

    // Enter the code and save the connection.
    await page.getByTestId('pairing-code-input').fill(code?.trim() ?? '');
    await page.getByTestId('save-connection-button').click();

    // Frontend: the paired device appears in the device list.
    const deviceRow = page.getByTestId('device-row');
    await expect(deviceRow.first()).toBeVisible();
    await expect(deviceRow.first()).toContainText(/READY|متصل/);

    // Backend: the device and connection are persisted.
    const { ok, status, body } = await apiJson(request, 'GET', '/api/connections/browser/devices');
    expect(ok, `GET /api/connections/browser/devices returned ${status}`).toBeTruthy();
    const devices = (body as any)?.devices ?? (body as any) ?? [];
    expect(Array.isArray(devices) && devices.length).toBeGreaterThan(0);
    expect((devices[0] as any)?.state).toMatch(/READY|CONNECTED/);
  });
});

/* -------------------------------------------------------------------------- */
/* Journey 3 — Agent CRUD: create an agent                                    */
/* -------------------------------------------------------------------------- */

test.describe('Journey 3 — Agent CRUD', () => {
  test('creates an agent through the UI and it is persisted with a version in the backend', async ({ page, request }) => {
    await page.goto('/agents');
    await expect(page.getByTestId('agents-heading')).toBeVisible();

    const before = await apiJson(request, 'GET', '/api/agents');
    const beforeCount = Array.isArray((before.body as any)?.agents) ? (before.body as any).agents.length : 0;

    // Frontend: open the create form and fill it.
    await page.getByTestId('create-agent-button').click();
    await page.getByTestId('agent-name-input').fill('Research Agent');
    await page.getByTestId('agent-goal-input').fill('Research and summarize topics.');
    await page.getByTestId('agent-runtime-select').selectOption('native');
    await page.getByTestId('save-agent-button').click();

    // Frontend: the new agent appears in the list.
    await expect(page.getByTestId('agent-row:has-text("Research Agent")')).toBeVisible();

    // Backend: the agent was created and an immutable version was saved.
    const after = await apiJson(request, 'GET', '/api/agents');
    expect(ok(after)).toBeTruthy();
    const afterCount = Array.isArray((after.body as any)?.agents) ? (after.body as any).agents.length : 0;
    expect(afterCount).toBe(beforeCount + 1);

    const agent = ((after.body as any)?.agents ?? []).find((a: any) => a.name === 'Research Agent');
    expect(agent).toBeTruthy();
    expect(agent.id).toBeTruthy();

    const versions = await apiJson(request, 'GET', `/api/agents/${agent.id}/versions`);
    expect(ok(versions)).toBeTruthy();
    expect(Array.isArray((versions.body as any)?.versions) && (versions.body as any).versions.length).toBeGreaterThan(0);
  });
});

function ok(r: { ok: boolean }) {
  return r.ok;
}

/* -------------------------------------------------------------------------- */
/* Journey 4 — Chat: send message, streaming, tool call, approval, history   */
/* -------------------------------------------------------------------------- */

test.describe('Journey 4 — Chat with streaming, tool call and approval', () => {
  test('sends a message, streams a reply, routes a tool call through approval and keeps history after reload (EN)', async ({ page, request }) => {
    await runChatJourney(page, request, 'en');
  });

  test('sends a message, streams a reply, routes a tool call through approval and keeps history after reload (AR)', async ({ page, request }) => {
    await runChatJourney(page, request, 'ar');
  });
});

async function runChatJourney(page, request, lang: 'en' | 'ar') {
  // Switch locale before loading so i18next renders the chosen language.
  await page.goto('/');
  await page.evaluate((lng) => {
    localStorage.setItem('i18nextLng', lng);
  }, lang);
  await page.reload();

  await page.getByTestId('chat-heading').first().waitFor();
  await expect(page.getByTestId('chat-heading').first()).toBeVisible();

  const send = lang === 'ar' ? 'أرسل رسالة' : 'Send a message';
  await page.getByTestId('message-input').fill(send);
  await page.getByTestId('send-button').click();

  // Frontend: a streaming message appears and the generating indicator shows.
  await expect(page.getByTestId('streaming-indicator')).toBeVisible();
  await expect(page.getByTestId('assistant-message')).toBeVisible({ timeout: 30_000 });

  // Backend: the run and its events are recorded.
  const runs = await apiJson(request, 'GET', '/api/runs');
  expect(ok(runs)).toBeTruthy();
  const run = ((runs.body as any)?.runs ?? []).slice(-1)[0];
  expect(run.id).toBeTruthy();

  const events = await apiJson(request, 'GET', `/api/runs/${run.id}/events`);
  expect(ok(events)).toBeTruthy();
  const eventTypes = ((events.body as any)?.events ?? []).map((e: any) => e.event_type);
  expect(eventTypes).toContain('run.started');
  expect(eventTypes).toContain('agent.stream');

  // Tool call appears and requires approval (SPEC §4.6 / §8.3-D).
  const toolCard = page.getByTestId('tool-call-card').first();
  await expect(toolCard).toBeVisible();
  await page.getByTestId('approve-tool-button').first().click();
  await expect(page.getByTestId('tool-result')).toBeVisible();

  // Reload: history must persist (SPEC §4.3 outbox/events).
  await page.reload();
  await expect(page.getByTestId('message-input')).toBeVisible();
  await expect(page.getByTestId('assistant-message').first()).toBeVisible();
}

/* -------------------------------------------------------------------------- */
/* Journey 5 — Run timeline / events                                          */
/* -------------------------------------------------------------------------- */

test.describe('Journey 5 — Run timeline', () => {
  test('shows the run timeline from the frontend and the events table from the backend', async ({ page, request }) => {
    await page.goto('/runs');
    await expect(page.getByTestId('runs-heading')).toBeVisible();

    // Pick the latest run row.
    const latestRun = page.getByTestId('run-row').first();
    await expect(latestRun).toBeVisible();
    await latestRun.click();

    // Frontend: timeline of events is rendered.
    await expect(page.getByTestId('timeline-list')).toBeVisible();
    await expect(page.getByTestId('timeline-event').first()).toBeVisible();

    // Backend: the same events are queryable and `sequence` is monotonic.
    const runId = await latestRun.getAttribute('data-run-id');
    expect(runId).toBeTruthy();

    const { ok, status, body } = await apiJson(request, 'GET', `/api/runs/${runId}/events`);
    expect(ok, `GET /api/runs/${runId}/events returned ${status}`).toBeTruthy();
    const events = (body as any)?.events ?? [];
    expect(Array.isArray(events) && events.length).toBeGreaterThan(0);

    const sequences = events.map((e: any) => e.sequence).filter((n: any) => typeof n === 'number');
    for (let i = 1; i < sequences.length; i++) {
      expect(sequences[i]).toBeGreaterThan(sequences[i - 1]);
    }
  });
});

/* -------------------------------------------------------------------------- */
/* Journey 6 — Approvals inbox                                                */
/* -------------------------------------------------------------------------- */

test.describe('Journey 6 — Approvals inbox', () => {
  test('approves a pending tool-call approval through the UI and the backend state changes', async ({ page, request }) => {
    await page.goto('/approvals');
    await expect(page.getByTestId('approvals-heading')).toBeVisible();

    const pending = page.getByTestId('approval-row:has-text("pending")').first();
    if ((await pending.count()) === 0) {
      test.skip(true, 'no pending approval available in this environment');
    }

    const approvalId = await pending.getAttribute('data-approval-id');
    expect(approvalId).toBeTruthy();

    await page.getByTestId('approve-approval-button').first().click();
    await expect(page.getByTestId('approval-toast')).toBeVisible();

    // Backend: the approval is now approved.
    const { ok, status, body } = await apiJson(request, 'GET', `/api/approvals/${approvalId}`);
    expect(ok, `GET /api/approvals/${approvalId} returned ${status}`).toBeTruthy();
    expect((body as any)?.status).toBe('approved');
  });
});

/* -------------------------------------------------------------------------- */
/* Journey 7 — Live Browser panel: waiting for user → resume                  */
/* -------------------------------------------------------------------------- */

test.describe('Journey 7 — Live Browser panel (waiting for user → resume)', () => {
  test('shows the "This agent needs you" banner and resumes after the human clears it', async ({ page, request }) => {
    await page.goto('/runs');
    await expect(page.getByTestId('runs-heading')).toBeVisible();

    const waiting = page.getByTestId('run-row:has-text("waiting_for_user")').first();
    if ((await waiting.count()) === 0) {
      test.skip(true, 'no run in waiting_for_user state in this environment');
    }

    // Open the Live Browser panel for that run.
    await waiting.getByTestId('open-live-browser-button').click();
    await expect(page.getByTestId('live-browser-panel')).toBeVisible();

    // Frontend: the waiting-for-user banner is shown (SPEC §6 Phase 1 / §8.3-C).
    await expect(
      page.getByTestId('waiting-for-user-banner')
    ).toContainText(/This agent needs you|يحتاج هذا الوكيل إليك/);
    await expect(page.getByTestId('resume-button')).toBeVisible();

    // Human clears the blocker and resumes.
    await page.getByTestId('resume-button').click();
    await expect(page.getByTestId('resumed-indicator')).toBeVisible();

    // Backend: the run state moved to resumed.
    const runId = await waiting.getAttribute('data-run-id');
    expect(runId).toBeTruthy();
    const { ok, status, body } = await apiJson(request, 'GET', `/api/runs/${runId}`);
    expect(ok, `GET /api/runs/${runId} returned ${status}`).toBeTruthy();
    expect((body as any)?.status).toMatch(/resumed|started/);
  });
});

/* -------------------------------------------------------------------------- */
/* Journey 8 — i18n / RTL: Arabic vs English                                  */
/* -------------------------------------------------------------------------- */

test.describe('Journey 8 — i18n and RTL direction', () => {
  test('switches language direction and labels between Arabic (RTL) and English (LTR)', async ({ page }) => {
    // Arabic (default) — RTL.
    await page.goto('/');
    await page.evaluate(() => localStorage.setItem('i18nextLng', 'ar'));
    await page.reload();
    await expect(page.getByTestId('app-shell')).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.getByTestId('language-switch')).toContainText(/عربية|Arabic/);

    // English — LTR.
    await page.getByTestId('language-switch').click();
    await page.getByTestId('lang-en').click();
    await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
    await expect(page.getByTestId('command-center-heading')).toBeVisible();
  });
});
