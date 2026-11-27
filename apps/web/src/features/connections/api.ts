/**
 * Connections/bridge REST calls — docs/API.md §7.2. Relative `/api/...` only.
 */
import { apiRequest } from '../../lib/api';
import type {
  ConnectionCreate,
  ConnectionOut,
  DeviceOut,
  PairingRequest,
  PairingResponse,
  ProviderOut,
  BrowserSessionOut,
} from './types';

export function listConnections(signal?: AbortSignal): Promise<ConnectionOut[]> {
  return apiRequest<ConnectionOut[]>('/api/connections', { signal });
}

export function createConnection(body: ConnectionCreate): Promise<ConnectionOut> {
  return apiRequest<ConnectionOut>('/api/connections', { method: 'POST', body });
}

export function listProviders(signal?: AbortSignal): Promise<ProviderOut[]> {
  return apiRequest<ProviderOut[]>('/api/providers', { signal });
}

export function listDevices(signal?: AbortSignal): Promise<DeviceOut[]> {
  return apiRequest<DeviceOut[]>('/api/devices', { signal });
}

/** Pair a bridge device. The response credential is shown once and never
 * stored client-side (docs/API.md §7.3). */
export function pairDevice(body: PairingRequest): Promise<PairingResponse> {
  return apiRequest<PairingResponse>('/api/devices/pair', { method: 'POST', body });
}

export function revokeDevice(deviceId: string): Promise<{ ok: boolean; message: string }> {
  return apiRequest<{ ok: boolean; message: string }>(
    `/api/devices/${encodeURIComponent(deviceId)}/revoke`,
    { method: 'POST' },
  );
}

export function listBrowserSessions(signal?: AbortSignal): Promise<BrowserSessionOut[]> {
  return apiRequest<BrowserSessionOut[]>('/api/browser-sessions', { signal });
}
