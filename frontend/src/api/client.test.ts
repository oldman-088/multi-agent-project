import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from './client';

afterEach(() => vi.restoreAllMocks());

describe('apiClient', () => {
  it('uses same-origin relative API paths and unwraps agent collections', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      JSON.stringify({ agents: [{ id: 'agent-1', name: 'Researcher' }] }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));

    await expect(apiClient.listAgents()).resolves.toEqual([{ id: 'agent-1', name: 'Researcher' }]);
    expect(fetchMock).toHaveBeenCalledWith('/api/agents', expect.objectContaining({ credentials: 'same-origin' }));
  });

  it('encodes conversation identifiers and sends the documented JSON body', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      JSON.stringify({ message: { id: 'm1', role: 'user', content: 'hello' } }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));

    await expect(apiClient.sendMessage('room/a', 'hello')).resolves.toMatchObject({ id: 'm1' });
    expect(fetchMock).toHaveBeenCalledWith('/api/conversations/room%2Fa/messages', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ content: 'hello' }),
    }));
  });

  it('surfaces useful API errors without losing their status', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: 'Not authorized' }), {
      status: 403,
      headers: { 'Content-Type': 'application/json' },
    }));

    await expect(apiClient.listAgents()).rejects.toMatchObject({ message: 'Not authorized', status: 403, name: 'ApiError' });
  });
});
