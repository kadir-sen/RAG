import axios from 'axios';
import { MOCK_ENABLED, mockAdapter } from '../mocks/adapter';

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 120_000,
  headers: { 'Content-Type': 'application/json' },
});

// Designer mode: answer every request from local fixtures instead of a backend.
// Disable by setting VITE_MOCK=false in .env (or VITE_API_URL to a real API).
if (MOCK_ENABLED) {
  apiClient.defaults.adapter = mockAdapter;
  // eslint-disable-next-line no-console
  console.info('[COAir] Designer mock mode is ON — all data is sample data.');
}

// Attach the active bearer token to every request. We read from localStorage
// directly to avoid importing the zustand store here (circular import: the
// store calls apiClient.post() to log in).
apiClient.interceptors.request.use((config) => {
  try {
    const raw = localStorage.getItem('coair-auth');
    if (raw) {
      const parsed = JSON.parse(raw) as { state?: { token?: string | null } };
      const token = parsed?.state?.token;
      if (token) {
        config.headers = config.headers ?? {};
        config.headers.Authorization = `Bearer ${token}`;
      }
    }
  } catch {
    // Ignore — request will go out unauthenticated and fail with 401 below.
  }
  return config;
});

// 401 → drop the session and bounce to /login so the user can re-authenticate.
// 402 / token_quota_exceeded is left for callers to handle (toast + bar).
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status: number | undefined = error?.response?.status;
    const url: string = error?.config?.url ?? '';
    if (status === 401 && !url.includes('/auth/login')) {
      try {
        localStorage.removeItem('coair-auth');
      } catch {
        // ignore
      }
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        window.location.assign('/login');
      }
    }
    return Promise.reject(error);
  },
);

export default apiClient;
