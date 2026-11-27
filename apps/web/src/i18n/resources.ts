/**
 * Translation resources.
 *
 * `en` is the reference catalogue: every other locale must contain **every**
 * key in `en` with a non-empty string value, and must not contain keys that
 * `en` does not have. `scripts/check-i18n.mjs` enforces this and fails the
 * build (``npm run i18n:check``) on any missing, empty, extra, non-string or
 * `{{placeholder}}`-mismatched entry.
 *
 * Keys are flat, dot-delimited strings (for example `connection.manager.title`)
 * so that a coverage diff is trivial to read. Groups:
 *   app.*        product chrome (skip link, language switcher, theme label)
 *   nav.*        primary navigation
 *   page.*       per-screen headings, descriptions and empty states
 *   connection.* Connection Manager (the Phase 1 acceptance screen)
 *   action.*     reusable button labels
 *   a11y.*       accessibility labels that screen readers announce
 *   format.*     locale-aware number/date wrappers shown in the UI
 *   error.*      user-facing error states
 */

import ar from './locales/ar.ts';
import en from './locales/en.ts';
import fa from './locales/fa.ts';
import type { Language } from './languages.ts';

/** Flat, string-valued translation catalogue. */
export type TranslationCatalogue = Readonly<Record<string, string>>;

/** All catalogues keyed by language. `en` defines the key set. */
export const TRANSLATIONS: Readonly<Record<Language, TranslationCatalogue>> = {
  ar,
  en,
  fa,
};

/** Namespace used by i18next; catalogues are flat so a single namespace is enough. */
export const DEFAULT_NAMESPACE = 'translation';
