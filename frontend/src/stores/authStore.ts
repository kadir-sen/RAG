import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AuthUser, LoginResponse, QuotaInfo } from '../types/api';
import apiClient from '../api/client';

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  status: 'idle' | 'loading' | 'error';
  error: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<void>;
  updateQuota: (quota: QuotaInfo | null) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      status: 'idle',
      error: null,

      async login(username, password) {
        set({ status: 'loading', error: null });
        try {
          const { data } = await apiClient.post<LoginResponse>('/auth/login', {
            username,
            password,
          });
          set({
            token: data.access_token,
            user: data.user,
            status: 'idle',
            error: null,
          });
        } catch (err: unknown) {
          let message = 'login_failed';
          if (typeof err === 'object' && err !== null) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const e = err as any;
            if (e.response?.status === 401) message = 'invalid_credentials';
            else if (e.response?.data?.detail) message = String(e.response.data.detail);
            else if (e.message) message = e.message;
          }
          set({ status: 'error', error: message });
          throw err;
        }
      },

      logout() {
        set({ token: null, user: null, status: 'idle', error: null });
      },

      async refreshMe() {
        if (!get().token) return;
        try {
          const { data } = await apiClient.get<{ user: AuthUser }>('/auth/me');
          set({ user: data.user });
        } catch {
          // Token likely invalid — clear it so the user is redirected to login.
          set({ token: null, user: null });
        }
      },

      updateQuota(quota) {
        if (!quota) return;
        const user = get().user;
        if (!user) return;
        set({
          user: {
            ...user,
            used_tokens: quota.used_tokens,
            token_limit: quota.token_limit,
            percent_remaining: quota.percent_remaining,
            plan_type: quota.plan_type,
            credits_total: quota.credits_total,
            credits_remaining: quota.credits_remaining,
            credits_used: quota.credits_used,
            credit_percent_remaining: quota.credit_percent_remaining,
            storage_used_bytes: quota.storage_used_bytes,
            storage_limit_bytes: quota.storage_limit_bytes,
            storage_percent_used: quota.storage_percent_used,
          },
        });
      },
    }),
    {
      name: 'coair-auth',
      partialize: (state) => ({ token: state.token, user: state.user }),
    },
  ),
);
