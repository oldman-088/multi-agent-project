/**
 * Language switcher (SPEC §8.2).
 *
 * Changing the language calls `i18n.changeLanguage`, which re-renders every
 * translated component through react-i18next and writes the new `lang`/`dir` to
 * `<html>` (see `i18n/i18next.ts` and `I18nProvider`).
 *
 * The control is a native `<select>` with a real `<label>`: no custom listbox,
 * so keyboard operation and screen-reader support come for free.
 */
import { useId } from 'react';
import { useTranslation } from 'react-i18next';

import { LANGUAGE_META, SUPPORTED_LANGUAGES, isLanguage, type Language } from '../i18n/languages.ts';

/** Narrows i18next's string to the shipped language set. */
function currentLanguage(language: string): Language {
  const base = language.split('-')[0] ?? 'ar';
  return isLanguage(base) ? base : 'ar';
}

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  const selectId = useId();
  const active = currentLanguage(i18n.language);

  return (
    <div className="nx-language">
      <label className="nx-visually-hidden" htmlFor={selectId}>
        {t('a11y.languageSwitcher')}
      </label>
      <select
        id={selectId}
        className="nx-select"
        value={active}
        aria-describedby={`${selectId}-current`}
        onChange={(event) => {
          void i18n.changeLanguage(event.target.value);
        }}
      >
        {SUPPORTED_LANGUAGES.map((language) => (
          <option key={language} value={language} lang={language} dir={LANGUAGE_META[language].direction}>
            {LANGUAGE_META[language].nativeName}
          </option>
        ))}
      </select>
      <span id={`${selectId}-current`} className="nx-visually-hidden" aria-live="polite">
        {t('app.language.current', { language: LANGUAGE_META[active].nativeName })}
      </span>
    </div>
  );
}
