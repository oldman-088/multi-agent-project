/**
 * Runs page (SPEC §8.3). The `events`/`runs` tables arrive in Phase 2; until
 * then the page shows the honest empty state.
 */
import { useTranslation } from 'react-i18next';

export function RunsPage() {
  const { t } = useTranslation();

  return (
    <>
      <div className="nx-page-header">
        <div>
          <h1>{t('page.runs.title')}</h1>
          <p>{t('page.runs.description')}</p>
        </div>
      </div>

      <section className="nx-empty" aria-labelledby="runs-empty">
        <h2 id="runs-empty" className="nx-card__title">
          {t('page.runs.empty')}
        </h2>
        <p className="nx-muted">{t('page.runs.description')}</p>
      </section>
    </>
  );
}
