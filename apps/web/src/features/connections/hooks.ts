/**
 * Connections data hooks (SPEC §8.4 — query hooks per screen region).
 */
import { useMutation, useQuery, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import {
  createConnection,
  listBrowserSessions,
  listConnections,
  listDevices,
  listProviders,
  pairDevice,
  revokeDevice,
} from './api';
import type {
  ConnectionCreate,
  ConnectionOut,
  DeviceOut,
  PairingRequest,
  PairingResponse,
  ProviderOut,
  BrowserSessionOut,
} from './types';

export const connectionsKeys = {
  all: ['connections'] as const,
  connections: () => ['connections', 'list'] as const,
  devices: () => ['connections', 'devices'] as const,
  providers: () => ['connections', 'providers'] as const,
  sessions: () => ['connections', 'sessions'] as const,
};

export function useConnections() {
  return useQuery<ConnectionOut[]>({
    queryKey: connectionsKeys.connections(),
    queryFn: ({ signal }) => listConnections(signal),
  });
}

export function useProviders() {
  return useQuery<ProviderOut[]>({
    queryKey: connectionsKeys.providers(),
    queryFn: ({ signal }) => listProviders(signal),
  });
}

export function useDevices() {
  return useQuery<DeviceOut[]>({
    queryKey: connectionsKeys.devices(),
    queryFn: ({ signal }) => listDevices(signal),
  });
}

export function useBrowserSessions() {
  return useQuery<BrowserSessionOut[]>({
    queryKey: connectionsKeys.sessions(),
    queryFn: ({ signal }) => listBrowserSessions(signal),
  });
}

function useInvalidateConnections(): () => Promise<void> {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: connectionsKeys.all });
}

export function usePairDevice(): UseMutationResult<PairingResponse, Error, PairingRequest> {
  const invalidate = useInvalidateConnections();
  return useMutation<PairingResponse, Error, PairingRequest>({
    mutationFn: (body) => pairDevice(body),
    onSuccess: invalidate,
  });
}

export function useRevokeDevice(): UseMutationResult<
  { ok: boolean; message: string },
  Error,
  string
> {
  const invalidate = useInvalidateConnections();
  return useMutation<{ ok: boolean; message: string }, Error, string>({
    mutationFn: (deviceId) => revokeDevice(deviceId),
    onSuccess: invalidate,
  });
}

export function useCreateConnection(): UseMutationResult<ConnectionOut, Error, ConnectionCreate> {
  const invalidate = useInvalidateConnections();
  return useMutation<ConnectionOut, Error, ConnectionCreate>({
    mutationFn: (body) => createConnection(body),
    onSuccess: invalidate,
  });
}
