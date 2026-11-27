import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';
import {
  applyDocumentLanguage,
  DEFAULT_LANGUAGE,
  isLanguage,
  SUPPORTED_LANGUAGES,
  type Language,
} from '../lib/direction';
import ar from './locales/ar.json';
import en from './locales/en.json';
import fa from './locales/fa.json';

export const LANGUAGE_STORAGE_KEY = 'nx.lang';

/** Reads the persisted language, falling back to Arabic (the default, Section 8.2). */
export function readStoredLanguage(): Language {
  try {
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (isLanguage(stored)) {
      return stored;
    }
  } catch {
    // Storage unavailable (private mode): fall back to the default language.
  }
  return DEFAULT_LANGUAGE;
}

function persistLanguage(language: string): void {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Storage unavailable: the language still applies for this session.
  }
}

let initialized = false;

/** Initializes i18next once with ar/en/fa resources and document direction sync. */
export async function initI18n(language: Language = readStoredLanguage()): Promise<typeof i18next> {
  if (initialized) {
    return i18next;
  }
  initialized = true;

  i18next.on('languageChanged', (lng) => {
    applyDocumentLanguage(lng);
    persistLanguage(lng);
  });

  await i18next.use(initReactI18next).init({
    resources: {
      ar: { common: ar },
      en: { common: en },
      fa: { common: fa },
    },
    lng: language,
    fallbackLng: DEFAULT_LANGUAGE,
    supportedLngs: [...SUPPORTED_LANGUAGES],
    defaultNS: 'common',
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
  });

  applyDocumentLanguage(i18next.language);
  return i18next;
}

export default i18next;
