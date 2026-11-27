/**
 * Application entry point: providers and routing only.
 *
 * Order: `<I18nProvider>` (translation + `<html lang/dir>` sync) must wrap the
 * router so every route renders translated content in the right direction from
 * the first paint.
 */
import '@fontsource/ibm-plex-sans-arabic/400.css';
import '@fontsource/ibm-plex-sans-arabic/600.css';
import '@fontsource/ibm-plex-sans-arabic/700.css';
import './styles/tokens.css';
import './styles/layout.css';
import './styles/components.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { App } from './App.tsx';
import { I18nProvider } from './i18n/I18nProvider.tsx';

const container = document.getElementById('root');
if (!container) throw new Error('Root container #root is missing from index.html');

createRoot(container).render(
  <StrictMode>
    <I18nProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </I18nProvider>
  </StrictMode>,
);
