/**
 * The single i18next instance used by the app.
 *
 * `missingKeyHandler` is wired so that a key missing at runtime is reported
 * loudly instead of silently rendering the key name: in development it throws,
 * so an un-translated string can never ship unnoticed. The build-time
 * completeness gate is `apps/web/scripts/check-i18n.mjs`.
 */

import i18next, { type i18n as I18nInstance } from 'i18next';

import { DEFAULT_LANGUAGE, LANGUAGE_STORAGE_KEY, isLanguage, type Language } from './languages.ts';
import { DEFAULT_NAMESPACE, TRANSLATIONS } from './resources.ts';
import { documentLanguageAttributes } from './direction.ts';

/** Options accepted by {@link createI18n}. */
export interface CreateI18nOptions {
  /** Initial language; defaults to Arabic. */
  readonly language?: Language;
  /** Persist the owner's choice to `localStorage`; defaults to true in a browser. */
  readonly persist?: boolean;
  /** Throw on a missing key instead of returning the key; defaults to `import.meta.env.DEV`. */
  readonly throwOnMissingKey?: boolean;
  /** Storage implementation (injected by tests). */
  readonly storage?: Pick<Storage, 'getItem' | 'setItem'> | undefined;
}

/** Read a stored language, tolerating private-mode storage errors. */
function readStoredLanguage(storage: Pick<Storage, 'getItem'> | undefined): Language | undefined {
  try {
    const value = storage?.getItem(LANGUAGE_STORAGE_KEY);
    return isLanguage(value) ? value : undefined;
  } catch {
    return undefined;
  }
}

/** Persist the language, tolerating private-mode storage errors. */
function writeStoredLanguage(storage: Pick<Storage, 'setItem'> | undefined, language: Language): void {
  try {
    storage?.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // A blocked storage is not fatal: the choice simply does not survive a reload.
  }
}

/** Create an isolated i18next instance (tests create one per case). */
export function createI18n(options: CreateI18nOptions = {}): I18nInstance {
  const browserStorage =
    options.storage ?? (typeof globalThis.localStorage === 'undefined' ? undefined : globalThis.localStorage);

  const initialLanguage = options.language ?? readStoredLanguage(browserStorage) ?? DEFAULT_LANGUAGE;
  const persist = options.persist ?? true;
  const throwOnMissingKey = options.throwOnMissingKey ?? true;

  const instance = i18next.createInstance();

  void instance.init({
    lng: initialLanguage,
    fallbackLng: DEFAULT_LANGUAGE,
    supportedLngs: Object.keys(TRANSLATIONS),
    defaultNS: DEFAULT_NAMESPACE,
    ns: [DEFAULT_NAMESPACE],
    resources: Object.fromEntries(
      Object.entries(TRANSLATIONS).map(([language, catalogue]) => [
        language,
        { [DEFAULT_NAMESPACE]: catalogue },
      ]),
    ),
    // React escapes rendered text itself; i18next must not HTML-escape values.
    interpolation: { escapeValue: false },
    returnNull: false,
    // The catalogues are flat dot-delimited keys, not nested objects.
    keySeparator: false,
    nsSeparator: false,
    initAsync: false,
    // i18next only invokes `missingKeyHandler` when saveMissing is on (we do not
    // have a backend to save to; the handler reports the gap and throws in dev).
    saveMissing: true,
    missingKeyHandler: (lngs, ns, key) => {
      const message = `[i18n] missing translation key "${key}" (namespace "${ns}") for ${lngs.join(', ')}`;
      if (throwOnMissingKey) throw new Error(message);
      // eslint-disable-next-line no-console -- loud in production, silent in tests
      console.error(message);
    },
  });

  instance.on('languageChanged', (language) => {
    if (isLanguage(language)) {
      if (persist) writeStoredLanguage(browserStorage, language);
      const attributes = documentLanguageAttributes(language);
      const doc = typeof globalThis.document === 'undefined' ? undefined : globalThis.document;
      if (doc?.documentElement) {
        doc.documentElement.setAttribute('lang', attributes.lang);
        doc.documentElement.setAttribute('dir', attributes.dir);
      }
    }
  });

  return instance;
}

/** The app-wide instance. Import this in components through `I18nProvider`. */
export const i18n = createI18n({ throwOnMissingKey: true });

export type { I18nInstance };
