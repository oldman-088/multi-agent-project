/**
 * Translation coverage rules.
 *
 * These pure functions are shared by the CLI (`apps/web/scripts/check-i18n.mjs`,
 * which fails the build) and the unit tests
 * (`apps/web/src/i18n/coverage.test.ts`), so the check and its tests can never
 * drift apart.
 *
 * A locale is valid when, compared with the reference locale:
 *   - every reference key exists,
 *   - every value is a non-empty, untrimmed-by-accident string,
 *   - no extra keys exist (dead keys hide translations that were never wired),
 *   - placeholders (`{{name}}`) match exactly — a missing placeholder silently
 *     breaks interpolation, an extra one is a copy/paste mistake.
 */

import { SUPPORTED_LANGUAGES, type Language } from './languages.ts';

/** A flat catalogue: dot-delimited key → translated string. */
export type Catalogue = Readonly<Record<string, string>>;

/** One concrete problem found in a locale. */
export interface CoverageIssue {
  readonly language: Language;
  readonly key: string;
  readonly kind: 'missing-key' | 'empty-value' | 'not-a-string' | 'extra-key' | 'placeholder-mismatch';
  readonly detail: string;
}

/** The `{{placeholder}}` names used by a string, in stable order. */
export function extractPlaceholders(value: string): string[] {
  const found = new Set<string>();
  for (const match of value.matchAll(/\{\{\s*([\w.]+)\s*\}\}/g)) {
    if (match[1]) found.add(match[1]);
  }
  return [...found].sort();
}

/** Every key of the reference catalogue, sorted for deterministic output. */
export function referenceKeys(reference: Catalogue): string[] {
  return Object.keys(reference).sort();
}

/**
 * Compare one locale against the reference catalogue.
 * Returns an empty array when the locale is complete and consistent.
 */
export function checkCatalogue(reference: Catalogue, locale: Catalogue, language: Language): CoverageIssue[] {
  const issues: CoverageIssue[] = [];

  for (const key of referenceKeys(reference)) {
    if (!Object.hasOwn(locale, key)) {
      issues.push({
        language,
        key,
        kind: 'missing-key',
        detail: `missing "${key}" in ${language}`,
      });
      continue;
    }

    const value: unknown = locale[key];

    if (typeof value !== 'string') {
      issues.push({
        language,
        key,
        kind: 'not-a-string',
        detail: `expected a string for "${key}" in ${language}, got ${typeof value}`,
      });
      continue;
    }

    if (value.trim() === '') {
      issues.push({
        language,
        key,
        kind: 'empty-value',
        detail: `empty translation for "${key}" in ${language}`,
      });
      continue;
    }

    const expected = extractPlaceholders(reference[key] ?? '');
    const actual = extractPlaceholders(value);
    const missing = expected.filter((name) => !actual.includes(name));
    const extra = actual.filter((name) => !expected.includes(name));

    if (missing.length > 0 || extra.length > 0) {
      const parts: string[] = [];
      if (missing.length > 0) parts.push(`missing ${missing.map((n) => `{{${n}}}`).join(', ')}`);
      if (extra.length > 0) parts.push(`unexpected ${extra.map((n) => `{{${n}}}`).join(', ')}`);
      issues.push({
        language,
        key,
        kind: 'placeholder-mismatch',
        detail: `placeholders for "${key}" in ${language}: ${parts.join('; ')}`,
      });
    }
  }

  for (const key of Object.keys(locale).sort()) {
    if (!Object.hasOwn(reference, key)) {
      issues.push({
        language,
        key,
        kind: 'extra-key',
        detail: `"${key}" exists in ${language} but not in the reference locale`,
      });
    }
  }

  return issues;
}

/** Languages that must be complete, excluding the reference locale itself. */
export function translatedLanguages(referenceLanguage: Language = 'en'): Language[] {
  return SUPPORTED_LANGUAGES.filter((language) => language !== referenceLanguage);
}

/**
 * Check every shipped locale against the reference locale.
 * `catalogues` maps every supported language to its catalogue.
 */
export function checkAllCatalogues(
  catalogues: Readonly<Record<Language, Catalogue>>,
  referenceLanguage: Language = 'en',
): CoverageIssue[] {
  const reference = catalogues[referenceLanguage];
  return translatedLanguages(referenceLanguage).flatMap((language) =>
    checkCatalogue(reference, catalogues[language], language),
  );
}

/** Human-readable one-line description of an issue, used by the CLI and tests. */
export function describeIssue(issue: CoverageIssue): string {
  return `[${issue.kind}] ${issue.detail}`;
}
