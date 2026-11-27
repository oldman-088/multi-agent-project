/**
 * Dark/light theme toggle (SPEC §8.1).
 *
 * The theme is a `data-theme` attribute on `<html>` and is persisted under
 * `nexus.theme`. Dark is the default. The button exposes `aria-pressed` and a
 * translated accessible name, and is keyboard operable as a native button.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'nexus.theme';

/** Read the stored theme, defaulting to dark. */
export function readTheme(): Theme {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

/** Apply the theme to `<html data-theme>`. */
export function applyTheme(theme: Theme, doc: Document | undefined = globalThis.document): Theme {
  doc?.documentElement.setAttribute('data-theme', theme);
  return theme;
}

export function ThemeToggle() {
  const { t } = useTranslation();
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    applyTheme(theme);
    try {
      globalThis.localStorage?.setItem(STORAGE_KEY, theme);
    } catch {
      // Storage may be unavailable in private mode; the theme still applies for this session.
    }
  }, [theme]);

  const next: Theme = theme === 'dark' ? 'light' : 'dark';

  return (
    <button
      type="button"
      className="nx-button"
      aria-pressed={theme === 'light'}
      data-testid="theme-toggle"
      onClick={() => setTheme(next)}
    >
      <span aria-hidden="true">{theme === 'dark' ? '☾' : '☀'}</span>
      {t(next === 'dark' ? 'app.theme.dark' : 'app.theme.light')}
    </button>
  );
}
