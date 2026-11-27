/**
 * Route table only — the app root does providers and routing and nothing else
 * (SPEC §8.3, "no god components").
 */
import { Route, Routes } from 'react-router-dom';

import { AppShell } from './components/AppShell.tsx';
import { AgentsPage } from './pages/AgentsPage.tsx';
import { ConnectionsPage } from './pages/ConnectionsPage.tsx';
import { DashboardPage } from './pages/DashboardPage.tsx';
import { NotFoundPage } from './pages/NotFoundPage.tsx';
import { RunsPage } from './pages/RunsPage.tsx';
import { SettingsPage } from './pages/SettingsPage.tsx';

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="connections" element={<ConnectionsPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
