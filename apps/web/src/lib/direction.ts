/** Supported UI languages and document direction helpers (Section 8.2). */

export const SUPPORTED_LANGUAGES = ['ar', 'en', 'fa'] as const;
export type Language = (typeof SUPPORTED_LANGUAGES)[number];

/** Arabic is the default language (Section 8.2). */
export const DEFAULT_LANGUAGE: Language = 'ar';

/** Languages that render right-to-left. */
export const RTL_LANGUAGES: ReadonlySet<Language> = new Set<Language>(['ar', 'fa']);

export function isLanguage(value: string | null | undefined): value is Language {
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(value ?? '');
}

export function isRtlLanguage(language: string): boolean {
  return RTL_LANGUAGES.has(language as Language);
}

/** Sets `lang` and `dir` on <html> from the active language (Section 8.2). */
export function applyDocumentLanguage(language: string): void {
  const lang = isLanguage(language) ? language : DEFAULT_LANGUAGE;
  document.documentElement.lang = lang;
  document.documentElement.dir = isRtlLanguage(lang) ? 'rtl' : 'ltr';
}
