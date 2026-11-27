import { useTranslation } from 'react-i18next';
import { Outlet } from 'react-router-dom';
import { MOD_KEY_LABEL } from '../../lib/platform';
import { useLanguage } from '../language/useLanguage';
import { useTheme } from '../theme/useTheme';
import { Header } from './Header';
import { Sidebar } from './Sidebar';

/** Application shell: skip link, header, sidebar and the routed outlet. */
export function AppShell() {
  const { t } = useTranslation();
  const { language, isRtl } = useLanguage();
  const { theme } = useTheme();

  return (
    <div className="flex min-h-screen flex-col bg-nx-bg text-nx-fg">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:start-2 focus:top-2 focus:z-nx-toast focus:rounded-nx-md focus:bg-nx-primary focus:px-3 focus:py-2 focus:text-nx-primary-fg"
      >
        {t('shell.skipToContent')}
      </a>

      <Header />

      <div className="flex flex-1">
        <Sidebar />
        <main id="main-content" tabIndex={-1} className="flex-1 p-4 focus:outline-none md:p-6">
          <Outlet />
        </main>
      </div>

      <footer className="border-t border-nx-border bg-nx-surface px-4 py-3 text-xs text-nx-fg-muted">
        <dl className="flex flex-wrap gap-x-6 gap-y-1">
          <div className="flex gap-2">
            <dt>{t('home.languageLabel')}:</dt>
            <dd>{t(`languages.${language}`)}</dd>
          </div>
          <div className="flex gap-2">
            <dt>{t('home.directionLabel')}:</dt>
            <dd>{isRtl ? t('home.rtl') : t('home.ltr')}</dd>
          </div>
          <div className="flex gap-2">
            <dt>{t('home.themeLabel')}:</dt>
            <dd>{t(`theme.${theme}`)}</dd>
          </div>
          <div className="flex gap-2">
            <dt>{t('palette.open')}:</dt>
            <dd className="font-mono">{MOD_KEY_LABEL}</dd>
          </div>
        </dl>
      </footer>
    </div>
  );
}
