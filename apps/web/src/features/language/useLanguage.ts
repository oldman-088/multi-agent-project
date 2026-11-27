import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  DEFAULT_LANGUAGE,
  isLanguage,
  isRtlLanguage,
  type Language,
} from '../../lib/direction';

/** Reads the active language and exposes a setter backed by i18next. */
export function useLanguage(): {
  language: Language;
  setLanguage: (language: Language) => void;
  isRtl: boolean;
} {
  const { i18n } = useTranslation();
  const language: Language = isLanguage(i18n.language) ? i18n.language : DEFAULT_LANGUAGE;

  const setLanguage = useCallback(
    (next: Language) => {
      void i18n.changeLanguage(next);
    },
    [i18n],
  );

  return { language, setLanguage, isRtl: isRtlLanguage(language) };
}
