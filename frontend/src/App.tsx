import { Component, Suspense, lazy } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AppShell from './layout/AppShell';
import ChatPage from './pages/ChatPage';

const SettingsModal = lazy(() => import('./components/shared/SettingsModal'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

class ErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean; error: Error | null }
> {
  state = { hasError: false, error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Application error:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="h-full flex items-center justify-center bg-[var(--bg-primary)]" role="alert">
          <div className="text-center p-8 max-w-md">
            <h1 className="text-xl font-semibold text-[var(--text-primary)] mb-3">
              Something went wrong
            </h1>
            <p className="text-sm text-[var(--text-secondary)] mb-6">
              {this.state.error?.message || 'An unexpected error occurred.'}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="px-6 py-2.5 bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white rounded-lg text-sm font-medium transition-colors"
            >
              Reload Application
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AppShell>
          <ChatPage />
        </AppShell>
        <Suspense fallback={null}>
          <SettingsModal />
        </Suspense>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
