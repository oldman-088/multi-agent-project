/** 404 page with a real route back to the dashboard. */
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

export function NotFoundPage() {
  const { t } = useTranslation();

  return (
    <section className="nx-empty" aria-labelledby="not-found">
      <h1 id="not-found">{t('error.notFound')}</h1>
      <Link className="nx-button" to="/">
        {t('nav.dashboard')}
      </Link>
    </section>
  );
}
