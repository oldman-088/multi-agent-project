/** Dark/light theme persistence (Section 8.1: themes switch at runtime and persist). */

export type Theme = 'dark' | 'light';

export const THEME_STORAGE_KEY = 'nx.theme';

export function isTheme(value: string | null | undefined): value is Theme {
  return value === 'dark' || value === 'light';
}

export function readStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : 'dark';
  } catch {
    // Storage unavailable (private mode): default to the dark operations theme.
    return 'dark';
  }
}

/** Applies the theme to <html data-theme> and persists it. */
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage unavailable: the theme still applies for this session.
  }
}
