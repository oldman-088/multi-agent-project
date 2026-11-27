import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { AgentsScreen } from './components/AgentsScreen';
import { mockApi, page, unmockApi, type MockRoute } from '../../test/mock-api';
import type { AgentDetail, AgentOut } from './types';

function agent(overrides: Partial<AgentOut> = {}): AgentOut {
  return {
    id: 'agt_1',
    slug: 'research-agent',
    name: 'وكيل البحث',
    description: '',
    role: 'backend',
    avatar_color: 'accent',
    is_enabled: true,
    is_archived: false,
    current_version: 1,
    runtime: 'native',
    connection_id: null,
    autonomy_level: null,
    created_at: '2026-11-27T10:00:00+00:00',
    updated_at: '2026-11-27T10:00:00+00:00',
    ...overrides,
  };
}

function agentDetail(base: AgentOut): AgentDetail {
  return {
    ...base,
    current_version_detail: {
      id: 'agv_1',
      agent_id: base.id,
      version: base.current_version,
      name: base.name,
      description: base.description,
      role: base.role,
      goal: 'البحث في المواضيع',
      instructions: 'اتبع SPEC',
      runtime: base.runtime,
      connection_id: null,
      model_config_json: {},
      tools: ['calc.evaluate'],
      limits: {},
      permissions: {},
      change_note: '',
      created_at: base.created_at,
    },
  };
}

function renderScreen(routes: MockRoute[]) {
  const api = mockApi(routes);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AgentsScreen />
    </QueryClientProvider>,
  );
  return api;
}

afterEach(() => {
  unmockApi();
});

describe('Agents screen (SPEC 8.3 — list + create form; RTL Arabic default)', () => {
  it('lists agents from GET /api/agents using a relative URL, in Arabic under RTL', async () => {
    const api = renderScreen([
      { path: '/api/agents', reply: () => ({ body: page([agent(), agent({ id: 'agt_2', name: 'وكيل الكتابة' })]) }) },
    ]);

    expect(await screen.findByTestId('agents-heading')).toHaveTextContent('الوكلاء');
    expect(document.documentElement.dir).toBe('rtl');

    const rows = await screen.findAllByTestId('agent-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('وكيل البحث');
    expect(rows[1]).toHaveTextContent('وكيل الكتابة');

    const listCall = api.callsTo('/api/agents')[0];
    expect(listCall.url).toBe('/api/agents');
    expect(listCall.url).not.toContain('http');
  });

  it('renders the empty state with the next action', async () => {
    renderScreen([{ path: '/api/agents', reply: () => ({ body: page([]) }) }]);

    expect(await screen.findByText('لا يوجد وكلاء بعد')).toBeInTheDocument();
    expect(screen.getByTestId('empty-create-agent-button')).toBeInTheDocument();
  });

  it('shows an error state with retry that recovers', async () => {
    const api = renderScreen([
      {
        path: '/api/agents',
        reply: ({ nth }) =>
          nth === 0
            ? { status: 500, body: { error: { code: 'http_error', message: 'down' } } }
            : { body: page([agent()]) },
      },
    ]);

    expect(await screen.findByRole('alert')).toHaveTextContent('down');
    await userEvent.click(screen.getByTestId('retry-button'));

    expect(await screen.findByTestId('agent-row')).toHaveTextContent('وكيل البحث');
    expect(api.callsTo('/api/agents').length).toBeGreaterThanOrEqual(2);
  });

  it('creates an agent through the form (POST /api/agents) and refreshes the list', async () => {
    const created = agent({ id: 'agt_new', name: 'Research Agent' });
    const api = renderScreen([
      {
        path: '/api/agents',
        reply: ({ nth }) => ({ body: page(nth === 0 ? [] : [created]) }),
      },
      { path: '/api/agents', method: 'POST', reply: () => ({ status: 201, body: created }) },
    ]);

    await screen.findByText('لا يوجد وكلاء بعد');
    await userEvent.click(screen.getByTestId('empty-create-agent-button'));

    await userEvent.type(screen.getByTestId('agent-name-input'), 'Research Agent');
    await userEvent.type(screen.getByTestId('agent-goal-input'), 'Research and summarize topics.');
    await userEvent.selectOptions(screen.getByTestId('agent-runtime-select'), 'software_team');
    await userEvent.click(screen.getByTestId('save-agent-button'));

    // The new agent shows up after the post-create refetch.
    expect(await screen.findByTestId('agent-row')).toHaveTextContent('Research Agent');

    const post = api.callsTo('/api/agents', 'POST')[0];
    expect(post.url).toBe('/api/agents');
    expect(post.body).toMatchObject({
      name: 'Research Agent',
      goal: 'Research and summarize topics.',
      runtime: 'software_team',
    });
  });

  it('requires a name before creating', async () => {
    const api = renderScreen([
      { path: '/api/agents', reply: () => ({ body: page([]) }) },
      { path: '/api/agents', method: 'POST', reply: () => ({ status: 201, body: agent() }) },
    ]);

    await screen.findByText('لا يوجد وكلاء بعد');
    await userEvent.click(screen.getByTestId('empty-create-agent-button'));
    await userEvent.click(screen.getByTestId('save-agent-button'));

    expect(await screen.findByText('الاسم مطلوب.')).toBeInTheDocument();
    expect(api.callsTo('/api/agents', 'POST')).toHaveLength(0);
  });

  it('edits an agent: PATCH carries the change note and the form preloads the version', async () => {
    const base = agent();
    const api = renderScreen([
      { path: '/api/agents', reply: () => ({ body: page([base]) }) },
      { path: '/api/agents/agt_1', reply: () => ({ body: agentDetail(base) }) },
      { path: '/api/agents/agt_1', method: 'PATCH', reply: () => ({ body: agent({ current_version: 2 }) }) },
    ]);

    const row = await screen.findByTestId('agent-row');
    await userEvent.click(within(row).getByTestId('edit-agent-button'));

    const nameInput = await screen.findByTestId('agent-name-input');
    await waitFor(() => expect(nameInput).toHaveValue('وكيل البحث'));
    await userEvent.type(screen.getByTestId('agent-change-note-input'), 'tighten instructions');
    await userEvent.click(screen.getByTestId('save-agent-button'));

    await waitFor(() => expect(api.callsTo('/api/agents/agt_1', 'PATCH')).toHaveLength(1));
    const patch = api.callsTo('/api/agents/agt_1', 'PATCH')[0];
    expect(patch.url).toBe('/api/agents/agt_1');
    expect(patch.body).toMatchObject({
      name: 'وكيل البحث',
      change_note: 'tighten instructions',
    });
  });
});
