/**
 * Router roots used by the app and by the tests.
 *
 * `MemoryRouter` keeps the a11y and screenshot fixtures on one shared provider
 * tree without touching `window.history`, while production uses the real
 * `BrowserRouter` (see `main.tsx`).
 */
import { MemoryRouter } from 'react-router-dom';

import { App } from './App.tsx';
import { I18nProvider } from './i18n/I18nProvider.tsx';
import { i18n as appI18n, type I18nInstance } from './i18n/i18next.ts';

/** Props of {@link AppRoot}. */
export interface AppRootProps {
  /** Route to render; defaults to the dashboard. */
  readonly initialPath?: string;
  /** Shared app instance; the a11y fixtures pass their own isolated one. */
  readonly instance?: I18nInstance;
}

export function AppRoot({ initialPath = '/', instance = appI18n }: AppRootProps) {
  return (
    <I18nProvider instance={instance}>
      <MemoryRouter initialEntries={[initialPath]}>
        <App />
      </MemoryRouter>
    </I18nProvider>
  );
}
