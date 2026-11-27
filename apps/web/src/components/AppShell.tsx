/**
 * Application shell: skip link, header (brand, language, theme), primary
 * navigation landmark and the `<main>` landmark every page renders into.
 *
 * The shell holds no data of its own; each page owns its content (SPEC §8.3,
 * "no god components").
 */
import { useTranslation } from 'react-i18next';
import { NavLink, Outlet } from 'react-router-dom';

import { MAIN_CONTENT_ID, SkipLink } from './SkipLink.tsx';
import { LanguageSwitcher } from './LanguageSwitcher.tsx';
import { ThemeToggle } from './ThemeToggle.tsx';

/** Primary destinations. Order is language-independent. */
const NAV_ITEMS = [
  { to: '/', key: 'nav.dashboard', end: true },
  { to: '/connections', key: 'nav.connections', end: false },
  { to: '/agents', key: 'nav.agents', end: false },
  { to: '/runs', key: 'nav.runs', end: false },
  { to: '/settings', key: 'nav.settings', end: false },
] as const;

export function AppShell() {
  const { t } = useTranslation();

  return (
    <div className="nx-app">
      {/* First focusable element on every page (SPEC §8.2). */}
      <SkipLink />
      <header className="nx-header">
        <div className="nx-brand">
          <span className="nx-brand__mark" aria-hidden="true">
            N
          </span>
          <span className="nx-brand__text">
            <span className="nx-brand__name">{t('app.name')}</span>
            <span className="nx-brand__tagline">{t('app.tagline')}</span>
          </span>
        </div>
        <div className="nx-header__tools">
          <LanguageSwitcher />
          <ThemeToggle />
        </div>
      </header>

      <nav className="nx-nav" aria-label={t('nav.label')}>
        <ul className="nx-nav__list">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink className="nx-nav__link" to={item.to} end={item.end}>
                {t(item.key)}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <main className="nx-main" id={MAIN_CONTENT_ID} tabIndex={-1} aria-label={t('a11y.mainContent')}>
        <Outlet />
      </main>

      <footer className="nx-footer" aria-hidden="false">
        <p className="nx-faint" lang="en" dir="ltr">
          NEXUS AGENT OS · local-first · en / ar / fa
        </p>
      </footer>
    </div>
  );
}
