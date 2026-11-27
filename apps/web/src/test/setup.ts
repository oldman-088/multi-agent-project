import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach } from 'vitest';
import { applyDocumentLanguage } from '../lib/direction';
import i18n, { initI18n } from '../i18n';

// The i18n singleton is idempotent — initialize once with the default
// language (Arabic) so every test file starts from a known state.
await initI18n('ar');

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
  // Reset direction/language between tests (i18n may have been switched).
  void i18n.changeLanguage('ar');
  applyDocumentLanguage('ar');
});

afterEach(() => {
  cleanup();
});
