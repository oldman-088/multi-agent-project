import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { createQueryClient } from './lib/queryClient';
import { AgentsScreen } from './features/agents/components/AgentsScreen';
import { ChatScreen } from './features/chat/components/ChatScreen';
import { CommandPalette } from './features/command-palette/CommandPalette';
import { CommandPaletteProvider } from './features/command-palette/CommandPaletteProvider';
import { ConnectionsScreen } from './features/connections/components/ConnectionsScreen';
import { HomeScreen } from './features/home/HomeScreen';
import { AppShell } from './features/shell/AppShell';
import { ThemeProvider } from './features/theme/ThemeProvider';

/**
 * App root: providers and routing only (Section 8.4 — no god components).
 * i18n is initialized in src/i18n before render (see main.tsx).
 */
const queryClient = createQueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <CommandPaletteProvider>
          <BrowserRouter>
            <Routes>
              <Route element={<AppShell />}>
                <Route path="/" element={<HomeScreen />} />
                <Route path="/agents" element={<AgentsScreen />} />
                <Route path="/chat" element={<ChatScreen />} />
                <Route path="/connections" element={<ConnectionsScreen />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
            {/* Uses useNavigate, so it must render inside the router. */}
            <CommandPalette />
          </BrowserRouter>
        </CommandPaletteProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
