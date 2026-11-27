/**
 * React binding for the i18next instance.
 *
 * `I18nProvider` publishes the instance through react-i18next (which also makes
 * every component re-render on `languageChanged`) and keeps `<html lang/dir>`
 * in sync with the active language for the whole app lifetime.
 */

import { useEffect, useMemo, type ReactNode } from 'react';
import { I18nextProvider } from 'react-i18next';

import { isLanguage, type Language } from './languages.ts';
import { syncDocumentLanguage } from './direction.ts';
import { i18n as defaultI18n, type I18nInstance } from './i18next.ts';

/** Props of {@link I18nProvider}. */
export interface I18nProviderProps {
  readonly children: ReactNode;
  /** Override the app instance (tests pass an isolated one). */
  readonly instance?: I18nInstance;
  /** Disable the `<html lang/dir>` sync (tests that assert on the DOM do their own). */
  readonly syncDocument?: boolean;
}

/**
 * Wrap the app once. The order matters: the provider must sit above every
 * component that calls `useTranslation()`, and the `dir`/`lang` sync must run
 * before the first paint of translated content.
 */
export function I18nProvider({ children, instance = defaultI18n, syncDocument = true }: I18nProviderProps) {
  useEffect(() => {
    if (!syncDocument) return;

    const language = isLanguage(instance.language) ? instance.language : 'ar';
    return syncDocumentLanguage(language, (listener) => {
      const onChanged = (next: string) => {
        if (isLanguage(next)) listener(next);
      };
      instance.on('languageChanged', onChanged);
      return () => {
        instance.off('languageChanged', onChanged);
      };
    });
  }, [instance, syncDocument]);

  return <I18nextProvider i18n={instance}>{children}</I18nextProvider>;
}

/** The active language, narrowed to the shipped set. */
export function useActiveLanguage(instance: I18nInstance = defaultI18n): Language {
  const language = instance.language.split('-')[0] ?? 'ar';
  return isLanguage(language) ? language : 'ar';
}

/** Stable list of the shipped languages for the switcher. */
export function useLanguageOptions(): { value: Language; nativeName: string; dir: 'rtl' | 'ltr' }[] {
  return useMemo(
    () => [
      { value: 'ar', nativeName: 'العربية', dir: 'rtl' },
      { value: 'en', nativeName: 'English', dir: 'ltr' },
      { value: 'fa', nativeName: 'فارسی', dir: 'rtl' },
    ],
    [],
  );
}
