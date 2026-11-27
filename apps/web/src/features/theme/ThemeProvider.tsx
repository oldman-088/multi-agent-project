import { useCallback, useEffect, useMemo, useState, type PropsWithChildren } from 'react';
import { applyTheme, readStoredTheme, type Theme } from '../../lib/theme';
import { ThemeContext } from './theme-context';

/** Applies the active theme to <html data-theme> and persists it (Section 8.1). */
export function ThemeProvider({ children }: PropsWithChildren) {
  const [theme, setThemeState] = useState<Theme>(() => readStoredTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((current) => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  const value = useMemo(
    () => ({ theme, setTheme, toggleTheme }),
    [theme, setTheme, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
