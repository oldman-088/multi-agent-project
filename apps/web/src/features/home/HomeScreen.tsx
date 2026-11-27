import { useTranslation } from 'react-i18next';
import { MOD_KEY_LABEL } from '../../lib/platform';
import { useLanguage } from '../language/useLanguage';
import { useTheme } from '../theme/useTheme';
import { useCommandPalette } from '../command-palette/useCommandPalette';

/** Phase 1 landing screen: shows the live i18n/theme state of the shell. */
export function HomeScreen() {
  const { t } = useTranslation();
  const { language, isRtl } = useLanguage();
  const { theme } = useTheme();
  const { open } = useCommandPalette();

  const state = [
    { label: t('home.languageLabel'), value: t(`languages.${language}`) },
    { label: t('home.directionLabel'), value: isRtl ? t('home.rtl') : t('home.ltr') },
    { label: t('home.themeLabel'), value: t(`theme.${theme}`) },
  ];

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold text-nx-fg">{t('home.heading')}</h1>
        <p className="text-sm text-nx-fg-muted">{t('home.description')}</p>
      </div>

      <dl className="grid gap-3 sm:grid-cols-3">
        {state.map((item) => (
          <div
            key={item.label}
            className="rounded-nx-lg border border-nx-border bg-nx-surface p-4"
          >
            <dt className="text-xs text-nx-fg-muted">{item.label}</dt>
            <dd className="mt-1 text-sm font-medium text-nx-fg">{item.value}</dd>
          </div>
        ))}
      </dl>

      <p className="text-sm text-nx-fg-muted">
        {t('home.openPaletteHint', { shortcut: MOD_KEY_LABEL })}{' '}
        <button
          type="button"
          onClick={open}
          className="font-medium text-nx-accent underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
        >
          {t('palette.open')}
        </button>
      </p>
    </div>
  );
}
