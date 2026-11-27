/**
 * Route table only — the app root does providers and routing and nothing else
 * (SPEC §8.3, "no god components").
 *
 * Paths come from `routes.ts` so the accessibility and screenshot matrices
 * cannot drift from the app: adding a page means adding one entry there, and
 * `routes.test.ts` fails if the page is not wired up or not reachable from the
 * primary navigation. React Router requires `<Route>` to be a *direct* child of
 * `<Routes>`, so the entries are written per route instead of through a wrapper
 * component.
 */
import type { JSX } from 'react';
import { Route, Routes } from 'react-router-dom';

import { i18n } from './i18n/i18next.ts';

import { AppShell } from './components/AppShell.tsx';
import { TranslationErrorBoundary } from './i18n/TranslationErrorBoundary.tsx';
import { AgentsPage } from './pages/AgentsPage.tsx';
import { ConnectionsPage } from './pages/ConnectionsPage.tsx';
import { DashboardPage } from './pages/DashboardPage.tsx';
import { NotFoundPage } from './pages/NotFoundPage.tsx';
import { RunsPage } from './pages/RunsPage.tsx';
import { SettingsPage } from './pages/SettingsPage.tsx';
import { MAIN_ROUTES } from './routes.ts';

/**
 * Page component per route name. `satisfies` makes a route without a page a
 * compile error, which is the first half of the "a new page cannot be
 * forgotten" guard; `routes.test.ts` is the other half.
 */
const PAGES = {
  dashboard: DashboardPage,
  connections: ConnectionsPage,
  agents: AgentsPage,
  runs: RunsPage,
  settings: SettingsPage,
} as const satisfies Record<(typeof MAIN_ROUTES)[number]['name'], () => JSX.Element>;

/** Resolve a route name to its component, failing loudly on a wiring mistake. */
function pageFor(name: string): () => JSX.Element {
  const page = (PAGES as Record<string, (() => JSX.Element) | undefined>)[name];
  if (!page) throw new Error(`No page component is wired for route "${name}" — update PAGES in App.tsx`);
  return page;
}

/**
 * Wrap a page so a crash inside translated content degrades to the boundary
 * panel *inside* the shell: header, navigation and skip link stay usable.
 */
function guarded(Page: () => JSX.Element) {
  return (
    <TranslationErrorBoundary language={i18n.language}>
      <Page />
    </TranslationErrorBoundary>
  );
}

/** The five main routes, in the order `routes.ts` declares them. */
function mainRoutes() {
  return MAIN_ROUTES.map((route) => {
    const Page = pageFor(route.name);
    return 'index' in route && route.index ? (
      <Route key={route.name} index element={guarded(Page)} />
    ) : (
      <Route key={route.name} path={route.path.replace(/^\//, '')} element={guarded(Page)} />
    );
  });
}

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        {mainRoutes()}
        <Route path="*" element={guarded(NotFoundPage)} />
      </Route>
    </Routes>
  );
}
