/**
 * Agents page (SPEC §8.3). Phase 1 has no agent storage yet, so the page states
 * the empty state honestly and shows what an agent will need.
 */
import { useTranslation } from 'react-i18next';

export function AgentsPage() {
  const { t } = useTranslation();

  return (
    <>
      <div className="nx-page-header">
        <div>
          <h1>{t('page.agents.title')}</h1>
          <p>{t('page.agents.description')}</p>
        </div>
      </div>

      <section className="nx-empty" aria-labelledby="agents-empty">
        <h2 id="agents-empty" className="nx-card__title">
          {t('page.agents.empty')}
        </h2>
        <p className="nx-muted">{t('connection.empty')}</p>
      </section>
    </>
  );
}
