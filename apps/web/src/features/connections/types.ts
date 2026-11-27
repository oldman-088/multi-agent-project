/**
 * Connections & bridge models — mirrors docs/API.md §7.1 and the backend
 * schemas in apps/backend/app/schemas/connections.py.
 */

export type ConnectionStatus = 'disabled' | 'enabled' | 'error';

export interface ConnectionOut {
  id: string;
  name: string;
  kind: string;
  status: ConnectionStatus;
  provider_slug: string;
  model: string | null;
  base_url: string | null;
  capabilities: Record<string, unknown>;
  terms_acknowledged: boolean;
  created_at: string;
}

export interface ConnectionCreate {
  name: string;
  provider_slug: string;
  kind: string;
  model?: string | null;
  base_url?: string | null;
  credential_id?: string | null;
  options?: Record<string, unknown>;
}

/** A paired bridge device (docs/API.md §7.2 GET /api/devices). */
export interface DeviceOut {
  id: string;
  label: string;
  userscript_version: string;
  revoked: boolean;
  last_seen_at: string | null;
  created_at: string;
}

/**
 * Pairing response — the credential is returned ONCE (docs/API.md §7.3):
 * only its hash is stored server-side.
 */
export interface PairingResponse {
  device_id: string;
  credential: string;
  expires_in: number;
}

export interface PairingRequest {
  label: string;
  userscript_version: string;
}

export type BrowserSessionState =
  | 'DISCONNECTED'
  | 'PAIRING_REQUIRED'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'AUTHENTICATED'
  | 'READY'
  | 'BUSY'
  | 'WAITING_FOR_USER'
  | 'RATE_LIMITED'
  | 'SESSION_EXPIRED'
  | 'PROVIDER_UNAVAILABLE'
  | 'ERROR';

export interface BrowserSessionOut {
  id: string;
  profile_id: string;
  provider_slug: string;
  state: BrowserSessionState;
  agent_page_state: string | null;
  url: string | null;
  title: string | null;
  queue_depth: number;
  last_error: string | null;
  granted_agent_id: string | null;
}

export interface ProviderOut {
  id: string;
  slug: string;
  display_name: string;
  kind: string;
  enabled: boolean;
  base_url: string | null;
}
