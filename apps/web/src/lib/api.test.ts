import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiUrl, apiRequest, readAuthToken, TOKEN_STORAGE_KEY } from './api';

function mockFetchOnce(status: number, body: unknown) {
  const fetchMock = vi.fn().mockImplementation(() =>
    Promise.resolve(
      new Response(body === null ? '' : JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('apiUrl (docs/API.md §1 — relative /api URLs only)', () => {
  it('builds relative /api paths with no host', () => {
    const url = apiUrl('/api/agents');
    expect(url).toBe('/api/agents');
    expect(url).not.toMatch(/^https?:/);
    expect(url).not.toContain('localhost');
    expect(url).not.toContain('127.0.0.1');
  });

  it('appends query parameters and skips undefined values', () => {
    expect(apiUrl('/api/runs', { status: 'running', limit: 50, offset: undefined })).toBe(
      '/api/runs?status=running&limit=50',
    );
  });

  it('refuses paths outside /api and absolute URLs', () => {
    expect(() => apiUrl('/health')).toThrow(/must start with \/api\//);
    expect(() => apiUrl('http://localhost:8000/api/agents')).toThrow(/must start with \/api\//);
    expect(() => apiUrl('https://example.com/api/agents')).toThrow(/must start with \/api\//);
  });
});

describe('apiRequest', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('calls fetch with a relative URL and JSON headers', async () => {
    const fetchMock = mockFetchOnce(200, { items: [], total: 0, limit: 50, offset: 0 });

    await apiRequest('/api/agents');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/agents');
    expect((init.headers as Record<string, string>)['Accept']).toBe('application/json');
    expect(init.method).toBe('GET');
  });

  it('attaches the bearer token from localStorage on authenticated calls', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok_123');
    const fetchMock = mockFetchOnce(200, {});

    await apiRequest('/api/agents');

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer tok_123');
  });

  it('sends no Authorization header on public routes or when logged out', async () => {
    const fetchMock = mockFetchOnce(200, { needs_setup: true });

    await apiRequest('/api/auth/setup-status', { auth: false });
    await apiRequest('/api/agents');

    for (const [, init] of fetchMock.mock.calls as unknown as [string, RequestInit][]) {
      expect(init.headers as Record<string, string>).not.toHaveProperty('Authorization');
    }
    expect(readAuthToken()).toBeNull();
  });

  it('serializes the JSON body and sets Content-Type', async () => {
    const fetchMock = mockFetchOnce(201, { id: 'agt_1' });

    await apiRequest('/api/agents', { method: 'POST', body: { name: 'Research' } });

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.body).toBe(JSON.stringify({ name: 'Research' }));
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('parses the error envelope into ApiError (docs/API.md §1.1)', async () => {
    mockFetchOnce(404, {
      error: { code: 'not_found', message: 'Agent not found', details: { agent_id: 'agt_9' } },
    });

    const failure = apiRequest('/api/agents/agt_9');

    await expect(failure).rejects.toBeInstanceOf(ApiError);
    await failure.catch((err: unknown) => {
      const apiError = err as ApiError;
      expect(apiError.status).toBe(404);
      expect(apiError.code).toBe('not_found');
      expect(apiError.message).toBe('Agent not found');
      expect(apiError.details).toEqual({ agent_id: 'agt_9' });
    });
  });

  it('falls back to an http_error code when the body is not the envelope', async () => {
    mockFetchOnce(502, '<html>bad gateway</html>');

    await expect(apiRequest('/api/agents')).rejects.toMatchObject({
      code: 'http_error',
      status: 502,
    });
  });
});
