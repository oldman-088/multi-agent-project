import { Languages, Moon, Search, Sun } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '../../components/ui/button';
import { SUPPORTED_LANGUAGES } from '../../lib/direction';
import { MOD_KEY_LABEL } from '../../lib/platform';
import { cn } from '../../lib/utils';
import { useLanguage } from '../language/useLanguage';
import { useTheme } from '../theme/useTheme';
import { useCommandPalette } from '../command-palette/useCommandPalette';

/** Top bar: brand, language switcher, theme toggle, palette trigger. */
export function Header() {
  const { t } = useTranslation();
  const { language, setLanguage } = useLanguage();
  const { theme, toggleTheme } = useTheme();
  const { open } = useCommandPalette();

  return (
    <header className="sticky top-0 z-nx-sticky flex h-14 items-center justify-between gap-4 border-b border-nx-border bg-nx-surface px-4">
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-semibold tracking-wide text-nx-fg">{t('app.title')}</span>
        <span className="hidden text-xs text-nx-fg-muted sm:inline">{t('app.tagline')}</span>
      </div>

      <div className="flex items-center gap-2">
        <div
          role="group"
          aria-label={t('shell.languageSelect')}
          className="flex items-center gap-1 rounded-nx-md border border-nx-border p-1"
        >
          <Languages className="mx-1 hidden h-4 w-4 text-nx-fg-muted sm:block" aria-hidden="true" />
          {SUPPORTED_LANGUAGES.map((code) => (
            <button
              key={code}
              type="button"
              aria-pressed={language === code}
              onClick={() => setLanguage(code)}
              className={cn(
                'rounded-nx-sm px-2 py-1 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus',
                language === code
                  ? 'bg-nx-primary text-nx-primary-fg'
                  : 'text-nx-fg-muted hover:bg-nx-surface-raised hover:text-nx-fg',
              )}
            >
              {t(`languages.${code}`)}
            </button>
          ))}
        </div>

        <Button
          variant="ghost"
          size="icon"
          aria-label={t(theme === 'dark' ? 'theme.light' : 'theme.dark')}
          onClick={toggleTheme}
        >
          {theme === 'dark' ? (
            <Sun className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Moon className="h-4 w-4" aria-hidden="true" />
          )}
        </Button>

        <Button variant="outline" size="sm" onClick={open} aria-label={t('palette.open')}>
          <Search className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="hidden md:inline">{t('palette.open')}</span>
          <kbd className="rounded-nx-sm border border-nx-border bg-nx-surface-raised px-1.5 py-0.5 font-mono text-[0.7rem] text-nx-fg-muted">
            {MOD_KEY_LABEL}
          </kbd>
        </Button>
      </div>
    </header>
  );
}
