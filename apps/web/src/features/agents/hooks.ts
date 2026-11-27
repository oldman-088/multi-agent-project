/**
 * Agent data hooks (SPEC §8.4 — each screen owns its data through query
 * hooks such as `useAgents()`). Query keys live here so run events can
 * invalidate exactly the queries they affect.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import {
  archiveAgent,
  createAgent,
  getAgent,
  listAgentVersions,
  listAgents,
  setAgentEnabled,
  updateAgent,
} from './api';
import type { AgentCreate, AgentDetail, AgentOut, AgentUpdate, AgentVersionOut } from './types';
import type { Page } from '../../lib/api';

export const agentsKeys = {
  all: ['agents'] as const,
  list: (includeArchived: boolean) => ['agents', 'list', includeArchived] as const,
  detail: (agentId: string) => ['agents', 'detail', agentId] as const,
  versions: (agentId: string) => ['agents', 'versions', agentId] as const,
};

export function useAgents(includeArchived = false) {
  return useQuery<Page<AgentOut>>({
    queryKey: agentsKeys.list(includeArchived),
    queryFn: ({ signal }) => listAgents({ includeArchived }, signal),
  });
}

export function useAgent(agentId: string | null) {
  return useQuery<AgentDetail>({
    queryKey: agentsKeys.detail(agentId ?? ''),
    queryFn: ({ signal }) => getAgent(agentId as string, signal),
    enabled: agentId !== null,
  });
}

export function useAgentVersions(agentId: string | null) {
  return useQuery<AgentVersionOut[]>({
    queryKey: agentsKeys.versions(agentId ?? ''),
    queryFn: ({ signal }) => listAgentVersions(agentId as string, signal),
    enabled: agentId !== null,
  });
}

function useInvalidateAgents(): () => Promise<void> {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: agentsKeys.all });
}

export function useCreateAgent(): UseMutationResult<AgentOut, Error, AgentCreate> {
  const invalidate = useInvalidateAgents();
  return useMutation<AgentOut, Error, AgentCreate>({
    mutationFn: (body) => createAgent(body),
    onSuccess: invalidate,
  });
}

export function useUpdateAgent(): UseMutationResult<AgentOut, Error, { id: string; body: AgentUpdate }> {
  const invalidate = useInvalidateAgents();
  return useMutation<AgentOut, Error, { id: string; body: AgentUpdate }>({
    mutationFn: ({ id, body }) => updateAgent(id, body),
    onSuccess: invalidate,
  });
}

export function useSetAgentEnabled(): UseMutationResult<AgentOut, Error, { id: string; enabled: boolean }> {
  const invalidate = useInvalidateAgents();
  return useMutation<AgentOut, Error, { id: string; enabled: boolean }>({
    mutationFn: ({ id, enabled }) => setAgentEnabled(id, enabled),
    onSuccess: invalidate,
  });
}

export function useArchiveAgent(): UseMutationResult<{ ok: boolean; message: string }, Error, string> {
  const invalidate = useInvalidateAgents();
  return useMutation<{ ok: boolean; message: string }, Error, string>({
    mutationFn: (id) => archiveAgent(id),
    onSuccess: invalidate,
  });
}
