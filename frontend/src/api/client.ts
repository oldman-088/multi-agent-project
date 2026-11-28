export type AgentRuntime = 'native' | 'langgraph' | string;

export interface Agent {
  id: string;
  name: string;
  description?: string | null;
  goal?: string | null;
  runtime?: AgentRuntime;
  enabled?: boolean;
  version?: number;
}

export interface CreateAgentInput {
  name: string;
  goal: string;
  runtime: AgentRuntime;
}

export interface Conversation {
  id: string;
  title?: string | null;
  agent_id?: string | null;
  created_at?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  run_id?: string | null;
  event_type?: string;
}

export interface RunEvent {
  id?: string;
  event_type: string;
  run_id?: string;
  message?: string;
  content?: string;
  data?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
    credentials: 'same-origin',
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown; message?: unknown } | null;
    const message = typeof body?.detail === 'string'
      ? body.detail
      : typeof body?.message === 'string'
        ? body.message
        : `Request failed (${response.status})`;
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function collection<T>(result: T[] | { agents?: T[]; conversations?: T[]; messages?: T[] }): T[] {
  if (Array.isArray(result)) return result;
  return result.agents ?? result.conversations ?? result.messages ?? [];
}

export const apiClient = {
  async listAgents(): Promise<Agent[]> {
    const result = await request<Agent[] | { agents: Agent[] }>('/api/agents');
    return collection(result);
  },

  async createAgent(input: CreateAgentInput): Promise<Agent> {
    const result = await request<Agent | { agent: Agent }>('/api/agents', {
      method: 'POST',
      body: JSON.stringify(input),
    });
    return 'agent' in result ? result.agent : result;
  },

  async listAgentVersions(agentId: string): Promise<unknown[]> {
    const result = await request<unknown[] | { versions: unknown[] }>(`/api/agents/${encodeURIComponent(agentId)}/versions`);
    return Array.isArray(result) ? result : result.versions;
  },

  async listConversations(): Promise<Conversation[]> {
    const result = await request<Conversation[] | { conversations: Conversation[] }>('/api/conversations');
    return collection(result);
  },

  async createConversation(): Promise<Conversation> {
    const result = await request<Conversation | { conversation: Conversation }>('/api/conversations', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    return 'conversation' in result ? result.conversation : result;
  },

  async listMessages(conversationId: string): Promise<ChatMessage[]> {
    const result = await request<ChatMessage[] | { messages: ChatMessage[] }>(
      `/api/conversations/${encodeURIComponent(conversationId)}/messages`,
    );
    return collection(result);
  },

  async sendMessage(conversationId: string, content: string): Promise<ChatMessage> {
    const result = await request<ChatMessage | { message: ChatMessage }>(
      `/api/conversations/${encodeURIComponent(conversationId)}/messages`,
      { method: 'POST', body: JSON.stringify({ content }) },
    );
    return 'message' in result ? result.message : result;
  },

  /** Subscribe to run events. URL construction stays here so screens never call the transport directly. */
  subscribeToRun(runId: string, onEvent: (event: RunEvent) => void, onError?: () => void): () => void {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/runs/${encodeURIComponent(runId)}`);
    socket.addEventListener('message', (message: MessageEvent<string>) => {
      try {
        const event = JSON.parse(message.data) as RunEvent;
        onEvent(event);
      } catch {
        onError?.();
      }
    });
    socket.addEventListener('error', () => onError?.());
    return () => socket.close();
  },
};
