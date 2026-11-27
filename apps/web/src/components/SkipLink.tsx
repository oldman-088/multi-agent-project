/**
 * Skip-to-content link (SPEC §8.2, first focusable element on every page).
 *
 * It is always rendered — never hidden with `display: none` — so keyboard and
 * screen-reader users can reach it; CSS moves it off-screen until focused.
 */
import { useTranslation } from 'react-i18next';

/** `id` of the `<main>` landmark the skip link targets. */
export const MAIN_CONTENT_ID = 'main-content';

export function SkipLink() {
  const { t } = useTranslation();

  return (
    <a className="nx-skip-link" href={`#${MAIN_CONTENT_ID}`}>
      {t('app.skipToContent')}
    </a>
  );
}
