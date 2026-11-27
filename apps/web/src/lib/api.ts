/**
 * Typed REST client for the AATM backend.
 *
 * Contract: docs/API.md (the single shared backend/frontend contract).
 * Frontend rule (AGENTS.md): only relative `/api/...` URLs — never
 * `localhost`/`127.0.0.1` or any absolute host. The dev server proxies them
 * (see vite.config.ts).
 *
 * This file is the documented JSON boundary: responses arrive as `unknown`
 * from `fetch` and are cast to the interfaces declared in each feature's
 * `types.ts`, which mirror the models of docs/API.md §4–§7.
 */

/** Pagination envelope used by every list endpoint (docs/API.md §1). */
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/** Error envelope used by every non-2xx response (docs/API.md §1.1). */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

/** A non-2xx response from the API, carrying the contract's error envelope. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

export interface RequestOptions {
  method?: HttpMethod;
  /** JSON request body; serialized with JSON.stringify. */
  body?: unknown;
  signal?: AbortSignal;
  /** Set to false for public routes — no Authorization header is sent. */
  auth?: boolean;
  /** Query parameters; undefined values are omitted. */
  query?: Record<string, string | number | boolean | undefined>;
}

/** localStorage key holding the bearer token (docs/API.md §1 "Auth"). */
export const TOKEN_STORAGE_KEY = 'nx.token';

export function readAuthToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

/**
 * Builds a relative `/api/...` URL with optional query parameters.
 * Throws on anything that would leave the API root — absolute URLs are a
 * frontend-rule violation and are refused at the boundary.
 */
export function apiUrl(
  path: string,
  query?: Record<string, string | number | boolean | undefined>,
): string {
  if (!path.startsWith('/api/')) {
    throw new Error(`API paths must start with /api/ (got "${path}")`);
  }
  if (/^[a-z][a-z0-9+.-]*:/i.test(path) || path.startsWith('//')) {
    throw new Error(`API paths must be relative (got "${path}")`);
  }
  if (!query) {
    return path;
  }
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null || !('error' in value)) {
    return false;
  }
  const err = (value as { error: unknown }).error;
  return (
    typeof err === 'object' &&
    err !== null &&
    typeof (err as { code?: unknown }).code === 'string' &&
    typeof (err as { message?: unknown }).message === 'string'
  );
}

/**
 * Performs a JSON request against the API and returns the parsed body.
 * Throws {@link ApiError} for any non-2xx response (envelope per §1.1).
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, auth = true, query } = options;

  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  if (auth) {
    const token = readAuthToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }

  const response = await fetch(apiUrl(path, query), {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text) as unknown;
    } catch {
      parsed = null;
    }
  }

  if (!response.ok) {
    if (isErrorBody(parsed)) {
      throw new ApiError(
        response.status,
        parsed.error.code,
        parsed.error.message,
        parsed.error.details ?? {},
      );
    }
    throw new ApiError(response.status, 'http_error', `HTTP ${response.status}`);
  }

  return parsed as T;
}
