import { vi } from 'vitest';

/** Recorded fetch call for assertions (URL must stay relative — frontend rule). */
export interface RecordedCall {
  url: string;
  method: string;
  body: unknown;
  headers: Record<string, string>;
}

export interface RouteReply {
  status?: number;
  body: unknown;
}

export interface MockRoute {
  /** Path without query string, e.g. '/api/agents'. */
  path: string;
  method?: string;
  /** Static reply, or a function for stateful mocks (nth call per route). */
  reply: RouteReply | ((call: { url: string; body: unknown; nth: number }) => RouteReply);
}

/**
 * Stubs global fetch with URL-routed JSON replies and records every call.
 * Test-only helper — routes mirror docs/API.md paths.
 */
export function mockApi(routes: MockRoute[]): {
  calls: RecordedCall[];
  callsTo: (path: string, method?: string) => RecordedCall[];
} {
  const calls: RecordedCall[] = [];
  const perRouteCount = new Map<string, number>();

  const fetchMock = vi.fn().mockImplementation(async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? 'GET').toUpperCase();
    const headers = (init?.headers ?? {}) as Record<string, string>;
    let body: unknown = null;
    if (typeof init?.body === 'string' && init.body.length > 0) {
      body = JSON.parse(init.body) as unknown;
    }
    calls.push({ url, method, body, headers });

    const pathname = url.split('?')[0];
    const route = routes.find(
      (candidate) => candidate.path === pathname && (candidate.method ?? 'GET') === method,
    );
    if (!route) {
      return new Response(JSON.stringify({ error: { code: 'not_found', message: `no mock for ${method} ${url}` } }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const key = `${method} ${route.path}`;
    const nth = perRouteCount.get(key) ?? 0;
    perRouteCount.set(key, nth + 1);
    const reply = typeof route.reply === 'function' ? route.reply({ url, body, nth }) : route.reply;
    return new Response(reply.body === undefined ? '' : JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });

  vi.stubGlobal('fetch', fetchMock);

  return {
    calls,
    callsTo: (path, method = 'GET') =>
      calls.filter((call) => call.url.split('?')[0] === path && call.method === method),
  };
}

export function unmockApi(): void {
  vi.unstubAllGlobals();
}

/** Minimal Page envelope (docs/API.md §1). */
export function page<T>(items: T[]): { items: T[]; total: number; limit: number; offset: number } {
  return { items, total: items.length, limit: 50, offset: 0 };
}
