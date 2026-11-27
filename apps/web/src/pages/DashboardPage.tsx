/**
 * Dashboard (SPEC §8.3): live state of the team, its connections and its runs.
 *
 * Phase 1 has no run data yet, so the page renders honest, explicitly labelled
 * state: a connection health summary and an empty state with the next action.
 * No placeholder buttons (SPEC §0, "buttons without behavior").
 */
import { useTranslation } from 'react-i18next';

import { formatDate, formatNumber, formatRelativeTime } from '../i18n/format.ts';
import { useActiveLanguage } from '../i18n/I18nProvider.tsx';
import { StatusBadge } from '../components/StatusBadge.tsx';

/** Snapshot the dashboard shows until the runs API is wired in Phase 2. */
const STARTED_AT = new Date('2026-11-27T00:00:00Z');

export function DashboardPage() {
  const { t } = useTranslation();
  const language = useActiveLanguage();
  const now = new Date('2026-11-27T12:00:00Z');

  const stats = [
    { key: 'agents', label: t('nav.agents'), unit: t('page.agents.count'), value: 0 },
    { key: 'connections', label: t('nav.connections'), unit: t('page.connections.count'), value: 0 },
    { key: 'runs', label: t('nav.runs'), unit: t('page.runs.count'), value: 0 },
  ];

  return (
    <>
      <div className="nx-page-header">
        <div>
          <h1>{t('page.dashboard.title')}</h1>
          <p>{t('page.dashboard.description')}</p>
        </div>
        <div className="nx-page-header__meta">
          <StatusBadge tone="success" label={t('app.status.online')} />
        </div>
      </div>

      <section className="nx-grid" aria-labelledby="dashboard-stats-heading">
        <h2 id="dashboard-stats-heading" className="nx-visually-hidden">
          {t('page.dashboard.title')}
        </h2>
        {stats.map((stat) => (
          <article className="nx-card" key={stat.key}>
            <h3 className="nx-card__title">{stat.label}</h3>
            {/* The number is locale-formatted (Arabic and Persian digits); the
                unit is the full translated phrase because a lone ٠ / ۰ is a
                dot and would read as an empty card. */}
            <p className="nx-count" data-testid={`stat-${stat.key}`}>
              <span className="nx-count__value">{formatNumber(stat.value, language)}</span>
              <span className="nx-count__unit">{stat.unit}</span>
            </p>
          </article>
        ))}
      </section>

      <section className="nx-panel" aria-labelledby="dashboard-facts-heading">
        <h2 id="dashboard-facts-heading">{t('page.dashboard.facts')}</h2>
        <dl className="nx-facts">
          <div className="nx-facts__row">
            <dt>{t('app.owner')}</dt>
            <dd>{t('app.organization')}</dd>
          </div>
          <div className="nx-facts__row">
            <dt>{t('page.dashboard.startedAt')}</dt>
            <dd>{formatDate(STARTED_AT, language)}</dd>
          </div>
          <div className="nx-facts__row">
            <dt>{t('page.dashboard.uptime')}</dt>
            <dd>{formatRelativeTime(now, language, STARTED_AT)}</dd>
          </div>
        </dl>
      </section>

      <section className="nx-empty" aria-labelledby="dashboard-empty-heading">
        <h2 id="dashboard-empty-heading" className="nx-card__title">
          {t('page.dashboard.empty')}
        </h2>
        <p className="nx-muted">{t('connection.empty')}</p>
      </section>
    </>
  );
}
