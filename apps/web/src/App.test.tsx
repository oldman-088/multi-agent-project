/**
 * Render smoke tests for the shell and every page in all three languages.
 *
 * They verify the behaviour the Playwright suite then checks in a real browser:
 * translation is applied, the skip link and nav landmarks exist, and the
 * `<html dir>` follows the active language.
 */
import { act, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AppRoot } from './AppRoot.tsx';
import { createI18n } from './i18n/i18next.ts';
import { LANGUAGE_STORAGE_KEY, type Language } from './i18n/languages.ts';
import { TRANSLATIONS } from './i18n/resources.ts';

/** Look up a shipped string, failing the importing test loudly if it is absent. */
function text(language: Language, key: string): string {
  const value = TRANSLATIONS[language][key];
  if (value === undefined) throw new Error(`missing test fixture key ${language}:${key}`);
  return value;
}

const ROUTES = [
  ['/', 'page.dashboard.title'],
  ['/connections', 'connection.title'],
  ['/agents', 'page.agents.title'],
  ['/runs', 'page.runs.title'],
  ['/settings', 'page.settings.title'],
] as const;

let instance: ReturnType<typeof createI18n> | undefined;

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  instance?.off('languageChanged');
  instance = undefined;
  document.documentElement.removeAttribute('dir');
  document.documentElement.removeAttribute('lang');
  document.documentElement.removeAttribute('data-theme');
});

function renderRoute(path: string, language: Language) {
  instance = createI18n({ language, persist: false, throwOnMissingKey: true });
  return render(<AppRoot initialPath={path} instance={instance} />);
}

describe.each(ROUTES)('route %s', (path, titleKey) => {
  it.each<Language>(['ar', 'en', 'fa'])('renders its %s title', (language) => {
    renderRoute(path, language);
    // A translation missing at render time would throw (missingKeyHandler), so
    // reaching this assertion already proves the page is fully translated.
    expect(screen.getByRole('heading', { level: 1, name: text(language, titleKey) })).toBeInTheDocument();
  });
});

describe('application shell', () => {
  it('renders the skip link as the first focusable element', () => {
    renderRoute('/', 'en');
    const skipLink = document.querySelector('.nx-skip-link');
    expect(skipLink).toHaveAccessibleName(text('en', 'app.skipToContent'));
    expect(skipLink).toHaveAttribute('href', '#main-content');

    const focusable = document.querySelectorAll('a[href], button, select, input, [tabindex]:not([tabindex="-1"])');
    expect(focusable[0]).toBe(skipLink);
  });

  it('exposes a labelled primary navigation landmark with the active page marked', () => {
    renderRoute('/connections', 'en');
    const nav = screen.getByRole('navigation', { name: text('en', 'nav.label') });
    const active = within(nav).getByRole('link', { name: text('en', 'nav.connections') });
    expect(active).toHaveAttribute('aria-current', 'page');
  });

  it('renders a main landmark targeted by the skip link', () => {
    renderRoute('/', 'ar');
    const main = screen.getByRole('main');
    expect(main).toHaveAttribute('id', 'main-content');
  });

  it('sets <html lang> and <html dir> from the active language (ar → rtl)', () => {
    renderRoute('/', 'ar');
    expect(document.documentElement.getAttribute('lang')).toBe('ar');
    expect(document.documentElement.getAttribute('dir')).toBe('rtl');
  });

  it('sets <html lang> and <html dir> from the active language (en → ltr)', () => {
    renderRoute('/', 'en');
    expect(document.documentElement.getAttribute('lang')).toBe('en');
    expect(document.documentElement.getAttribute('dir')).toBe('ltr');
  });

  it('switches translation and direction at runtime when the language changes', async () => {
    renderRoute('/settings', 'ar');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(text('ar', 'page.settings.title'));

    await act(async () => {
      await instance?.changeLanguage('en');
    });

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(text('en', 'page.settings.title'));
    expect(document.documentElement.getAttribute('dir')).toBe('ltr');
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull();
  });

  it('lists the three languages in the switcher with their native names', () => {
    renderRoute('/settings', 'en');
    // The shell and the settings panel both render a language switcher.
    const [select] = screen.getAllByRole('combobox');
    expect(select).toBeDefined();
    const options = within(select!).getAllByRole('option');
    expect(options.map((option) => option.textContent)).toEqual(['العربية', 'English', 'فارسی']);
    expect(select).toHaveValue('en');
  });

  it('advances the browser-connection wizard and marks completed steps ready', () => {
    renderRoute('/connections', 'en');
    expect(screen.getAllByText('Step 1 of 5').length).toBeGreaterThan(0);

    const continueButton = screen.getByRole('button', { name: text('en', 'action.continue') });
    act(() => {
      continueButton.click();
    });

    expect(screen.getAllByText('Step 2 of 5').length).toBeGreaterThan(0);
    expect(screen.getAllByText(text('en', 'connection.state.ready')).length).toBeGreaterThan(0);
  });

  it('renders the 404 page for an unknown route', () => {
    renderRoute('/no-such-page', 'fa');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(text('fa', 'error.notFound'));
  });
});
