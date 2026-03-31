import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AppShell from './layout/AppShell';
import ChatPage from './pages/ChatPage';
import SettingsModal from './components/shared/SettingsModal';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppShell>
        <ChatPage />
      </AppShell>
      <SettingsModal />
    </QueryClientProvider>
  );
}
