/**
 * `<html lang>` / `<html dir>` synchronisation.
 *
 * SPEC §8.2: "Set `<html dir>` and `lang` from the active language." The values
 * are therefore derived here from the active language and never written by hand
 * in `index.html` or in a component.
 *
 * The module keeps two flavours of the same logic:
 *   - `documentLanguageAttributes(language)` — pure, testable, no DOM;
 *   - `applyDocumentLanguage(language, doc)` — writes the attributes and
 *     returns what it wrote (so callers can assert on it).
 */

import { DEFAULT_LANGUAGE, LANGUAGE_META, isLanguage, type Direction, type Language } from './languages.ts';

/** The attributes that must exist on `<html>` for a given language. */
export interface DocumentLanguageAttributes {
  readonly lang: string;
  readonly dir: Direction;
}

/** Derive `lang` and `dir` from the active language. Pure function. */
export function documentLanguageAttributes(language: Language): DocumentLanguageAttributes {
  return {
    lang: isLanguage(language) ? LANGUAGE_META[language].bcp47 : LANGUAGE_META[DEFAULT_LANGUAGE].bcp47,
    dir: LANGUAGE_META[isLanguage(language) ? language : DEFAULT_LANGUAGE].direction,
  };
}

/**
 * Write the active language onto a document element.
 *
 * Returns the attributes that were written so the caller (or a test) can assert
 * on them without re-reading the DOM.
 */
export function applyDocumentLanguage(language: Language, doc: Document | undefined = globalThis.document): DocumentLanguageAttributes {
  const attributes = documentLanguageAttributes(language);

  if (doc?.documentElement) {
    doc.documentElement.setAttribute('lang', attributes.lang);
    doc.documentElement.setAttribute('dir', attributes.dir);
  }

  return attributes;
}

/**
 * Keep `<html lang/dir>` in sync with the active language for the lifetime of
 * the app: re-applies on every change and once immediately.
 *
 * `subscribe` is injected so the same code path is used by i18next and by tests
 * without pulling the i18next singleton into this module.
 */
export function syncDocumentLanguage(
  initialLanguage: Language,
  subscribe: (listener: (language: Language) => void) => () => void,
  doc: Document | undefined = globalThis.document,
): () => void {
  applyDocumentLanguage(initialLanguage, doc);

  const unsubscribe = subscribe((language) => {
    applyDocumentLanguage(language, doc);
  });

  return () => {
    unsubscribe();
  };
}
