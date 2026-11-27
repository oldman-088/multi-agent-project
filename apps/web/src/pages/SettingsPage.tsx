/**
 * Settings page (SPEC §8.3). It hosts the language picker that drives
 * `<html lang/dir>` and shows the live document attributes so the direction
 * change is verifiable by the owner (and by the a11y/screenshot tests).
 */
import { useTranslation } from 'react-i18next';

import { LanguageSwitcher } from '../components/LanguageSwitcher.tsx';
import { useActiveLanguage } from '../i18n/I18nProvider.tsx';
import { formatDate, formatNumber, intlLocale } from '../i18n/format.ts';
import { LANGUAGE_META } from '../i18n/languages.ts';

const SAMPLE_DATE = new Date('2026-11-27T00:00:00Z');

export function SettingsPage() {
  const { t } = useTranslation();
  const language = useActiveLanguage();
  const meta = LANGUAGE_META[language];

  return (
    <>
      <div className="nx-page-header">
        <div>
          <h1>{t('page.settings.title')}</h1>
          <p>{t('page.settings.description')}</p>
        </div>
      </div>

      <section className="nx-panel" aria-labelledby="settings-language">
        <h2 id="settings-language">{t('page.settings.language')}</h2>
        <p className="nx-muted">{t('page.settings.languageHint')}</p>
        <LanguageSwitcher />
        <dl className="nx-facts">
          <div className="nx-facts__row">
            <dt>{t('app.language.label')}</dt>
            <dd data-testid="active-language">
              {meta.nativeName} · <span className="nx-mono">{meta.bcp47}</span>
            </dd>
          </div>
          <div className="nx-facts__row">
            <dt>{t('page.settings.theme')}</dt>
            <dd data-testid="direction">
              <span className="nx-mono">{meta.direction}</span>
            </dd>
          </div>
          <div className="nx-facts__row">
            <dt>{t('format.number')}</dt>
            <dd className="nx-mono" data-testid="intl-locale">
              {intlLocale(language)} · {formatNumber(1234567.89, language)}
            </dd>
          </div>
          <div className="nx-facts__row">
            <dt>{t('format.date')}</dt>
            <dd>{formatDate(SAMPLE_DATE, language)}</dd>
          </div>
        </dl>
      </section>
    </>
  );
}
