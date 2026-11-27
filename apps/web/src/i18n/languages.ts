/**
 * Locale catalogue types and the single source of truth for the languages the
 * NEXUS AGENT OS web app ships: Arabic (default), English and Persian.
 *
 * `ar` and `fa` are right-to-left; `en` is left-to-right. The active language
 * drives both `lang` and `dir` on the `<html>` element (see `direction.ts` and
 * the `useDocumentLanguage` hook) — the two values are never hard-coded in a
 * component or in `index.html`.
 */

/** Languages shipped with the product (SPEC §8.2). */
export const SUPPORTED_LANGUAGES = ['ar', 'en', 'fa'] as const;

/** A language tag the app knows how to render. */
export type Language = (typeof SUPPORTED_LANGUAGES)[number];

/** Text direction a language renders in. */
export type Direction = 'rtl' | 'ltr';

/** Arabic is the product default (SPEC §4.2, §8.2). */
export const DEFAULT_LANGUAGE: Language = 'ar';

/** `localStorage` key that persists the owner's language choice. */
export const LANGUAGE_STORAGE_KEY = 'nexus.language';

/**
 * Language metadata used by the switcher, the `<html lang/dir>` sync and the
 * screenshot matrix. `nativeName` is always written in its own script so the
 * language picker is readable to a speaker of that language.
 */
export const LANGUAGE_META: Readonly<Record<Language, { readonly nativeName: string; readonly englishName: string; readonly direction: Direction; readonly bcp47: string }>> = {
  ar: { nativeName: 'العربية', englishName: 'Arabic', direction: 'rtl', bcp47: 'ar' },
  en: { nativeName: 'English', englishName: 'English', direction: 'ltr', bcp47: 'en' },
  fa: { nativeName: 'فارسی', englishName: 'Persian', direction: 'rtl', bcp47: 'fa' },
};

/** True when `value` is one of the shipped language tags. */
export function isLanguage(value: unknown): value is Language {
  return typeof value === 'string' && (SUPPORTED_LANGUAGES as readonly string[]).includes(value);
}

/** Direction for a language; used for `<html dir>` and for the ESLint-safe layouts. */
export function directionOf(language: Language): Direction {
  return LANGUAGE_META[language].direction;
}

/**
 * Pick the initial language: an explicitly stored choice wins, then the
 * browser's preferred languages, then the Arabic default.
 */
export function resolveInitialLanguage(
  storedLanguage: string | null | undefined,
  navigatorLanguages: readonly string[] = [],
): Language {
  if (isLanguage(storedLanguage)) return storedLanguage;

  for (const tag of navigatorLanguages) {
    // "ar-EG" → "ar", "fa-IR" → "fa", "en-GB" → "en".
    const base = tag.toLowerCase().split('-')[0];
    if (isLanguage(base)) return base;
  }

  return DEFAULT_LANGUAGE;
}
