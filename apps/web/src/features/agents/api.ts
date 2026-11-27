/**
 * Agents REST calls — docs/API.md §4.2. All paths are relative `/api/...`.
 */
import { apiRequest, type Page } from '../../lib/api';
import type { AgentCreate, AgentDetail, AgentOut, AgentUpdate, AgentVersionOut } from './types';

export interface ListAgentsParams {
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}

export function listAgents(params: ListAgentsParams = {}, signal?: AbortSignal): Promise<Page<AgentOut>> {
  return apiRequest<Page<AgentOut>>('/api/agents', {
    signal,
    query: {
      include_archived: params.includeArchived ? true : undefined,
      limit: params.limit,
      offset: params.offset,
    },
  });
}

export function getAgent(agentId: string, signal?: AbortSignal): Promise<AgentDetail> {
  return apiRequest<AgentDetail>(`/api/agents/${encodeURIComponent(agentId)}`, { signal });
}

export function createAgent(body: AgentCreate): Promise<AgentOut> {
  return apiRequest<AgentOut>('/api/agents', { method: 'POST', body });
}

export function updateAgent(agentId: string, body: AgentUpdate): Promise<AgentOut> {
  return apiRequest<AgentOut>(`/api/agents/${encodeURIComponent(agentId)}`, {
    method: 'PATCH',
    body,
  });
}

export function setAgentEnabled(agentId: string, enabled: boolean): Promise<AgentOut> {
  return apiRequest<AgentOut>(`/api/agents/${encodeURIComponent(agentId)}/enable`, {
    method: 'POST',
    query: { enabled },
  });
}

export function archiveAgent(agentId: string): Promise<{ ok: boolean; message: string }> {
  return apiRequest<{ ok: boolean; message: string }>(
    `/api/agents/${encodeURIComponent(agentId)}`,
    { method: 'DELETE' },
  );
}

export function listAgentVersions(
  agentId: string,
  signal?: AbortSignal,
): Promise<AgentVersionOut[]> {
  return apiRequest<AgentVersionOut[]>(
    `/api/agents/${encodeURIComponent(agentId)}/versions`,
    { signal },
  );
}
