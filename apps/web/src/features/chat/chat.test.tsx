import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ChatScreen } from './components/ChatScreen';
import { mockApi, page, unmockApi, type MockRoute } from '../../test/mock-api';
import type { ConversationOut, EventOut, MessageOut, RunOut } from './types';
import type { AgentOut } from '../agents/types';

function agent(): AgentOut {
  return {
    id: 'agt_1',
    slug: 'assistant',
    name: 'المساعد',
    description: '',
    role: 'chat',
    avatar_color: 'accent',
    is_enabled: true,
    is_archived: false,
    current_version: 1,
    runtime: 'native',
    connection_id: null,
    autonomy_level: null,
    created_at: '2026-11-27T10:00:00+00:00',
    updated_at: '2026-11-27T10:00:00+00:00',
  };
}

function conversation(): ConversationOut {
  return {
    id: 'conv_1',
    agent_id: 'agt_1',
    title: 'الدردشة الأولى',
    is_archived: false,
    last_message_at: null,
    created_at: '2026-11-27T10:00:00+00:00',
  };
}

function run(): RunOut {
  return {
    id: 'run_1',
    agent_id: 'agt_1',
    agent_version_id: null,
    conversation_id: 'conv_1',
    connection_id: null,
    status: 'running',
    trigger: 'chat',
    directive: 'مرحبا',
    last_sequence: 0,
    step_count: 0,
    tool_call_count: 0,
    error: null,
    started_at: null,
    finished_at: null,
    created_at: '2026-11-27T10:00:00+00:00',
  };
}

function event(
  sequence: number,
  event_type: string,
  payload: Record<string, unknown> = {},
): EventOut {
  return {
    event_id: `evt_${sequence}`,
    event_version: 1,
    organization_id: 'org_1',
    run_id: 'run_1',
    task_id: null,
    agent_id: 'agt_1',
    correlation_id: null,
    sequence,
    event_type,
    timestamp: `2026-11-27T12:00:0${Math.min(sequence, 9)}+00:00`,
    source_runtime: 'native',
    payload,
  };
}

const streamBatches: EventOut[][] = [
  [
    event(1, 'run.started'),
    event(2, 'agent.stream', { message_id: 'msg_live', delta: 'Hello ' }),
    event(3, 'agent.stream', { message_id: 'msg_live', delta: 'there' }),
  ],
  [
    event(4, 'tool.execution.started', { tool: 'calc.evaluate', outcome: 'running' }),
    event(5, 'approval.requested', {
      approval_id: 'apr_1',
      tool: 'calc.evaluate',
      reason: 'level 0 asks for every tool call',
    }),
  ],
  [
    event(6, 'tool.execution.completed', {
      tool: 'calc.evaluate',
      outcome: 'success',
      duration_ms: 12,
      result: { value: 4 },
    }),
    event(7, 'agent.message', { message_id: 'msg_live', content: 'Hello there' }),
    event(8, 'run.completed'),
  ],
];

function streamRoutes(): MockRoute {
  return {
    path: '/api/runs/run_1/events',
    reply: ({ nth }) => ({ body: streamBatches[Math.min(nth, streamBatches.length - 1)] }),
  };
}

function renderScreen(routes: MockRoute[]) {
  const api = mockApi(routes);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ChatScreen />
    </QueryClientProvider>,
  );
  return api;
}

afterEach(() => {
  unmockApi();
});

describe('Chat screen (SPEC 8.3-D — streaming + tool approvals, RTL Arabic)', () => {
  it('sends a message, streams the reply live and follows the event cursor', async () => {
    const api = renderScreen([
      { path: '/api/agents', reply: () => ({ body: page([agent()]) }) },
      { path: '/api/conversations', reply: () => ({ body: page([]) }) },
      { path: '/api/conversations', method: 'POST', reply: () => ({ status: 201, body: conversation() }) },
      { path: '/api/conversations/conv_1/messages', reply: () => ({ body: [] }) },
      { path: '/api/conversations/conv_1/messages', method: 'POST', reply: () => ({ status: 201, body: {} as MessageOut }) },
      { path: '/api/runs', method: 'POST', reply: () => ({ status: 201, body: run() }) },
      streamRoutes(),
    ]);

    expect(await screen.findByTestId('chat-heading')).toHaveTextContent('الدردشة');
    expect(document.documentElement.dir).toBe('rtl');

    // Wait until the agent is loaded and the composer is interactive.
    await waitFor(() => expect(screen.getByTestId('chat-agent-select')).toHaveValue('agt_1'));
    await userEvent.type(screen.getByTestId('message-input'), 'مرحبا');
    await userEvent.click(screen.getByTestId('send-button'));

    // The live reply streams in with the typing indicator.
    const assistant = await screen.findByTestId('assistant-message');
    await waitFor(() => expect(assistant).toHaveTextContent('Hello there'), { timeout: 4000 });
    expect(api.callsTo('/api/conversations', 'POST')[0].url).toBe('/api/conversations');
    expect(api.callsTo('/api/conversations/conv_1/messages', 'POST')[0].body).toEqual({
      content: 'مرحبا',
    });
    const runCall = api.callsTo('/api/runs', 'POST')[0];
    expect(runCall.url).toBe('/api/runs');
    expect(runCall.body).toMatchObject({
      agent_id: 'agt_1',
      directive: 'مرحبا',
      conversation_id: 'conv_1',
      trigger: 'chat',
    });

    // Cursor protocol: after_sequence advances and all URLs stay relative.
    await waitFor(
      () => {
        const cursors = api
          .callsTo('/api/runs/run_1/events')
          .map((call) => call.url)
          .filter((url) => url.includes('after_sequence=3'));
        expect(cursors.length).toBeGreaterThan(0);
      },
      { timeout: 4000 },
    );
    for (const call of api.callsTo('/api/runs/run_1/events')) {
      expect(call.url).not.toContain('http');
      expect(call.url).toContain('after_sequence=');
    }
  });

  it('routes a tool call through the inline approval card (POST /api/approvals/…/decide)', async () => {
    const api = renderScreen([
      { path: '/api/agents', reply: () => ({ body: page([agent()]) }) },
      { path: '/api/conversations', reply: () => ({ body: page([]) }) },
      { path: '/api/conversations', method: 'POST', reply: () => ({ status: 201, body: conversation() }) },
      { path: '/api/conversations/conv_1/messages', reply: () => ({ body: [] }) },
      { path: '/api/conversations/conv_1/messages', method: 'POST', reply: () => ({ status: 201, body: {} as MessageOut }) },
      { path: '/api/runs', method: 'POST', reply: () => ({ status: 201, body: run() }) },
      streamRoutes(),
      {
        path: '/api/approvals/apr_1/decide',
        method: 'POST',
        reply: () => ({
          body: {
            id: 'apr_1',
            kind: 'tool_call',
            status: 'approved',
            run_id: 'run_1',
            agent_id: 'agt_1',
            tool_slug: 'calc.evaluate',
            requested_payload: {},
            reason: 'level 0 asks for every tool call',
            decided_by: 'usr_1',
            decided_at: '2026-11-27T12:01:00+00:00',
            decision_note: null,
            created_at: '2026-11-27T12:00:00+00:00',
          },
        }),
      },
    ]);

    await waitFor(() => expect(screen.getByTestId('chat-agent-select')).toHaveValue('agt_1'));
    await userEvent.type(screen.getByTestId('message-input'), 'مرحبا');
    await userEvent.click(screen.getByTestId('send-button'));

    const toolCard = await screen.findByTestId('tool-call-card', {}, { timeout: 4000 });
    expect(toolCard).toHaveTextContent('calc.evaluate');

    const approve = await screen.findByTestId('approve-tool-button', {}, { timeout: 4000 });
    await userEvent.click(approve);

    await waitFor(
      () => expect(api.callsTo('/api/approvals/apr_1/decide', 'POST')).toHaveLength(1),
      { timeout: 4000 },
    );
    const decision = api.callsTo('/api/approvals/apr_1/decide', 'POST')[0];
    expect(decision.url).toBe('/api/approvals/apr_1/decide');
    expect(decision.body).toMatchObject({ approve: true });

    // Once the run completes, the tool result is rendered and streaming stops.
    expect(await screen.findByTestId('tool-result', {}, { timeout: 4000 })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument(), {
      timeout: 4000,
    });
  });

  it('restores conversation history after reload (persisted messages endpoint)', async () => {
    const saved: MessageOut[] = [
      {
        id: 'msg_1',
        conversation_id: 'conv_1',
        run_id: null,
        role: 'user',
        content: 'مرحبا',
        tool_calls: [],
        attachments: [],
        usage: null,
        sequence: 1,
        created_at: '2026-11-27T10:00:00+00:00',
      },
      {
        id: 'msg_2',
        conversation_id: 'conv_1',
        run_id: 'run_1',
        role: 'assistant',
        content: 'Hello there',
        tool_calls: [],
        attachments: [],
        usage: null,
        sequence: 2,
        created_at: '2026-11-27T10:00:01+00:00',
      },
    ];
    renderScreen([
      { path: '/api/agents', reply: () => ({ body: page([agent()]) }) },
      { path: '/api/conversations', reply: () => ({ body: page([conversation()]) }) },
      { path: '/api/conversations/conv_1/messages', reply: () => ({ body: saved }) },
    ]);

    await userEvent.click(await screen.findByTestId('conversation-row'));

    expect(await screen.findByTestId('user-message')).toHaveTextContent('مرحبا');
    const assistant = await screen.findByTestId('assistant-message');
    expect(assistant).toHaveTextContent('Hello there');
    expect(screen.getByTestId('message-list')).toBeInTheDocument();
  });
});
