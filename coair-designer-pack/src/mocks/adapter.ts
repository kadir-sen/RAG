// ─────────────────────────────────────────────────────────────────────────
// Axios mock adapter for offline "designer mode".
//
// When VITE_MOCK is enabled (default in this designer pack), client.ts swaps
// the real network transport for this adapter, so every API call is answered
// from local fixtures instead of hitting a backend. Turn it off by setting
// VITE_MOCK=false in .env (or pointing VITE_API_URL at a real backend).
// ─────────────────────────────────────────────────────────────────────────
import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { ROUTES, type MockCtx } from './routes';

// Toggle: on unless explicitly disabled.
export const MOCK_ENABLED =
  import.meta.env.VITE_MOCK !== 'false' && import.meta.env.VITE_MOCK !== '0';

function normalizePath(config: InternalAxiosRequestConfig): { path: string; query: URLSearchParams } {
  let url = config.url ?? '';
  const base = config.baseURL ?? '';
  if (base && url.startsWith(base)) url = url.slice(base.length);
  // also tolerate an absolute '/api/...' if baseURL wasn't joined
  if (url.startsWith('/api/')) url = url.slice(4);
  const [pathPart, queryPart] = url.split('?');
  const query = new URLSearchParams(queryPart ?? '');
  // axios params object → merge in
  if (config.params && typeof config.params === 'object') {
    for (const [k, v] of Object.entries(config.params)) {
      if (v != null) query.set(k, String(v));
    }
  }
  return { path: pathPart || '/', query };
}

function parseBody(config: InternalAxiosRequestConfig): unknown {
  const { data } = config;
  if (data == null) return undefined;
  if (typeof data === 'string') {
    try { return JSON.parse(data); } catch { return data; }
  }
  return data; // FormData or already-parsed object
}

// Network-ish latency so loading states are visible to the designer.
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const mockAdapter: AxiosAdapter = async (config) => {
  const method = (config.method ?? 'get').toUpperCase();
  const { path, query } = normalizePath(config as InternalAxiosRequestConfig);
  const body = parseBody(config as InternalAxiosRequestConfig);

  const route = ROUTES.find((r) => r.method === method && r.pattern.test(path));

  await delay(140 + Math.floor(Math.random() * 220));

  const respond = (data: unknown, status = 200): AxiosResponse => ({
    data,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    headers: {},
    config,
    request: {},
  });

  if (!route) {
    // eslint-disable-next-line no-console
    console.warn(`[mock] no handler for ${method} ${path} — returning empty.`);
    return respond({}, 200);
  }

  const match = route.pattern.exec(path);
  const ctx: MockCtx = { params: match ? match.slice(1) : [], query, body };
  const data = route.handler(ctx);
  return respond(data ?? {}, 200);
};
