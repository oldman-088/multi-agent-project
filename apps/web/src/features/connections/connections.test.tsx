import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ConnectionsScreen } from './components/ConnectionsScreen';
import { mockApi, unmockApi, type MockRoute } from '../../test/mock-api';
import type { BrowserSessionOut, ConnectionOut, DeviceOut, ProviderOut } from './types';

function device(overrides: Partial<DeviceOut> = {}): DeviceOut {
  return {
    id: 'dev_1',
    label: 'Chrome — العمل',
    userscript_version: '1.0.0',
    revoked: false,
    last_seen_at: '2026-11-27T10:00:00+00:00',
    created_at: '2026-11-27T09:00:00+00:00',
    ...overrides,
  };
}

function connection(): ConnectionOut {
  return {
    id: 'conn_1',
    name: 'Chrome — العمل',
    kind: 'browser_session',
    status: 'enabled',
    provider_slug: 'mock',
    model: null,
    base_url: null,
    capabilities: {},
    terms_acknowledged: true,
    created_at: '2026-11-27T10:00:00+00:00',
  };
}

function provider(): ProviderOut {
  return {
    id: 'prv_1',
    slug: 'mock',
    display_name: 'Mock',
    kind: 'browser_session',
    enabled: true,
    base_url: null,
  };
}

function session(): BrowserSessionOut {
  return {
    id: 'bsess_1',
    profile_id: 'prf_1',
    provider_slug: 'mock',
    state: 'READY',
    agent_page_state: null,
    url: 'https://mock.example/chat',
    title: null,
    queue_depth: 0,
    last_error: null,
    granted_agent_id: null,
  };
}

function baseRoutes(): MockRoute[] {
  return [
    { path: '/api/devices', reply: () => ({ body: [device()] }) },
    { path: '/api/connections', reply: () => ({ body: [connection()] }) },
    { path: '/api/providers', reply: () => ({ body: [provider()] }) },
    { path: '/api/browser-sessions', reply: () => ({ body: [session()] }) },
  ];
}

function renderScreen(routes: MockRoute[]) {
  const api = mockApi(routes);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ConnectionsScreen />
    </QueryClientProvider>,
  );
  return api;
}

afterEach(() => {
  unmockApi();
});

describe('Connections screen (SPEC 8.3-I — bridge pairing)', () => {
  it('lists paired devices, saved connections and sessions (Arabic RTL)', async () => {
    renderScreen(baseRoutes());

    expect(await screen.findByTestId('connections-heading')).toHaveTextContent('الاتصالات');
    expect(document.documentElement.dir).toBe('rtl');

    const row = await screen.findByTestId('device-row');
    expect(row).toHaveTextContent('Chrome — العمل');
    // Active devices show the READY/connected badge.
    expect(row).toHaveTextContent('متصل');
    expect(screen.getByTestId('connection-row')).toHaveTextContent('mock');
    expect(screen.getByTestId('session-state')).toHaveTextContent('READY');
  });

  it('pairs a bridge device and saves the connection through /api', async () => {
    const api = renderScreen([
      ...baseRoutes(),
      {
        path: '/api/devices/pair',
        method: 'POST',
        reply: () => ({
          status: 201,
          body: { device_id: 'dev_2', credential: 'pair-ab12cd34', expires_in: 300 },
        }),
      },
      {
        path: '/api/connections',
        method: 'POST',
        reply: () => ({ status: 201, body: connection() }),
      },
    ]);

    await screen.findByTestId('connections-heading');
    await userEvent.click(screen.getByTestId('start-pairing-button'));

    await userEvent.type(await screen.findByTestId('device-label-input'), 'Chrome — المنزل');
    await userEvent.click(screen.getByTestId('pair-device-button'));

    // The one-time credential is displayed (6+ chars) and shown exactly once.
    const code = await screen.findByTestId('pairing-code-display');
    expect(code).toHaveTextContent('pair-ab12cd34');
    const pairCall = api.callsTo('/api/devices/pair', 'POST')[0];
    expect(pairCall.url).toBe('/api/devices/pair');
    expect(pairCall.body).toEqual({ label: 'Chrome — المنزل', userscript_version: '1.0.0' });

    // Saving is gated on confirming the pairing code.
    const saveButton = screen.getByTestId('save-connection-button');
    expect(saveButton).toBeDisabled();
    await userEvent.type(screen.getByTestId('pairing-code-input'), 'wrong-code');
    expect(saveButton).toBeDisabled();
    await userEvent.clear(screen.getByTestId('pairing-code-input'));
    await userEvent.type(screen.getByTestId('pairing-code-input'), 'pair-ab12cd34');
    expect(saveButton).toBeEnabled();

    await userEvent.click(saveButton);
    await waitFor(() => expect(api.callsTo('/api/connections', 'POST')).toHaveLength(1));
    const saved = api.callsTo('/api/connections', 'POST')[0];
    expect(saved.url).toBe('/api/connections');
    expect(saved.body).toMatchObject({
      name: 'Chrome — المنزل',
      provider_slug: 'mock',
      kind: 'browser_session',
    });

    // Dialog closes and the device list is refreshed.
    await waitFor(() => expect(screen.queryByTestId('pair-device-dialog')).not.toBeInTheDocument());
  });

  it('revokes a device via the bridge revoke endpoint', async () => {
    const api = renderScreen([
      ...baseRoutes(),
      {
        path: '/api/devices/dev_1/revoke',
        method: 'POST',
        reply: () => ({ body: { ok: true, message: 'revoked' } }),
      },
    ]);

    const row = await screen.findByTestId('device-row');
    await userEvent.click(within(row).getByTestId('revoke-device-button'));

    await waitFor(() => expect(api.callsTo('/api/devices/dev_1/revoke', 'POST')).toHaveLength(1));
    expect(api.callsTo('/api/devices/dev_1/revoke', 'POST')[0].url).toBe(
      '/api/devices/dev_1/revoke',
    );
  });

  it('shows the error state with retry when the device list fails', async () => {
    renderScreen([
      {
        path: '/api/devices',
        reply: ({ nth }) =>
          nth === 0
            ? { status: 500, body: { error: { code: 'http_error', message: 'down' } } }
            : { body: [device()] },
      },
      ...baseRoutes().filter((route) => route.path !== '/api/devices'),
    ]);

    expect(await screen.findByRole('alert')).toHaveTextContent('down');
    await userEvent.click(screen.getByTestId('retry-button'));
    expect(await screen.findByTestId('device-row')).toBeInTheDocument();
  });
});
