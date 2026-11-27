/**
 * Chat REST calls — docs/API.md §4.2 (conversations/messages) and §5.2
 * (runs/events/approvals). All paths are relative `/api/...`.
 */
import { apiRequest, type Page } from '../../lib/api';
import type {
  ApprovalOut,
  ConversationOut,
  EventOut,
  MessageOut,
  RunOut,
} from './types';

export interface CreateConversationBody {
  agent_id: string;
  title?: string;
}

export function listConversations(
  params: { agentId?: string; limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<Page<ConversationOut>> {
  return apiRequest<Page<ConversationOut>>('/api/conversations', {
    signal,
    query: {
      agent_id: params.agentId,
      limit: params.limit,
      offset: params.offset,
    },
  });
}

export function createConversation(body: CreateConversationBody): Promise<ConversationOut> {
  return apiRequest<ConversationOut>('/api/conversations', { method: 'POST', body });
}

export function listMessages(
  conversationId: string,
  limit?: number,
  signal?: AbortSignal,
): Promise<MessageOut[]> {
  return apiRequest<MessageOut[]>(
    `/api/conversations/${encodeURIComponent(conversationId)}/messages`,
    { signal, query: { limit } },
  );
}

export function sendMessage(
  conversationId: string,
  body: { content: string; attachments?: unknown[] },
): Promise<MessageOut> {
  return apiRequest<MessageOut>(
    `/api/conversations/${encodeURIComponent(conversationId)}/messages`,
    { method: 'POST', body },
  );
}

export interface CreateRunBody {
  agent_id: string;
  directive: string;
  conversation_id?: string | null;
  trigger?: 'manual' | 'chat' | 'schedule' | 'file_watch' | 'git_event';
  idempotency_key?: string;
}

export function createRun(body: CreateRunBody): Promise<RunOut> {
  return apiRequest<RunOut>('/api/runs', { method: 'POST', body });
}

/**
 * Event cursor fetch — `after_sequence` is exclusive (docs/API.md §5.2), so
 * paging with the last seen sequence never repeats an event.
 */
export function listRunEvents(
  runId: string,
  afterSequence: number,
  limit?: number,
  signal?: AbortSignal,
): Promise<EventOut[]> {
  return apiRequest<EventOut[]>(`/api/runs/${encodeURIComponent(runId)}/events`, {
    signal,
    query: { after_sequence: afterSequence, limit },
  });
}

export function decideApproval(
  approvalId: string,
  body: { approve: boolean; note?: string },
): Promise<ApprovalOut> {
  return apiRequest<ApprovalOut>(`/api/approvals/${encodeURIComponent(approvalId)}/decide`, {
    method: 'POST',
    body,
  });
}

export function listApprovals(
  params: { status?: string; runId?: string; limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<Page<ApprovalOut>> {
  return apiRequest<Page<ApprovalOut>>('/api/approvals', {
    signal,
    query: {
      status: params.status,
      run_id: params.runId,
      limit: params.limit,
      offset: params.offset,
    },
  });
}
