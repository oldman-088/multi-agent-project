/**
 * Tests for the i18n completeness rules and for the shipped catalogues.
 *
 * These are the same rules `scripts/check-i18n.mjs` enforces in CI, so a
 * regression in the check is caught here as well as by the CLI.
 */
import { describe, expect, it } from 'vitest';

import {
  checkAllCatalogues,
  checkCatalogue,
  describeIssue,
  extractPlaceholders,
  referenceKeys,
  translatedLanguages,
  type Catalogue,
} from './coverage.ts';
import { SUPPORTED_LANGUAGES, LANGUAGE_META, directionOf, resolveInitialLanguage } from './languages.ts';
import { TRANSLATIONS } from './resources.ts';

const reference: Catalogue = {
  'page.title': 'Title',
  'page.count': '{{count}} items',
  'page.greeting': 'Hello {{name}}, you have {{count}} tasks',
};

describe('shipped catalogues', () => {
  it('ships exactly Arabic, English and Persian', () => {
    expect([...SUPPORTED_LANGUAGES]).toEqual(['ar', 'en', 'fa']);
    expect(Object.keys(TRANSLATIONS).sort()).toEqual(['ar', 'en', 'fa']);
  });

  it('has no coverage issue in any translated locale', () => {
    expect(checkAllCatalogues(TRANSLATIONS, 'en')).toEqual([]);
  });

  for (const language of translatedLanguages()) {
    it(`has the same key set as en in ${language}`, () => {
      expect(Object.keys(TRANSLATIONS[language]).sort()).toEqual(Object.keys(TRANSLATIONS.en).sort());
    });
  }

  it('has a real, non-Latin translation for representative Arabic keys', () => {
    // Guards against copy-pasting the English value as a placeholder translation.
    expect(TRANSLATIONS.ar['nav.dashboard']).not.toBe(TRANSLATIONS.en['nav.dashboard']);
    expect(TRANSLATIONS.ar['nav.dashboard']).toMatch(/[\u0600-\u06FF]/);
    expect(TRANSLATIONS.fa['nav.dashboard']).toMatch(/[\u0600-\u06FF]/);
  });

  it('uses Persian-specific letters somewhere in the Persian catalogue (پ چ ژ گ)', () => {
    const corpus = Object.values(TRANSLATIONS.fa).join(' ');
    expect(corpus).toMatch(/[پچژگ]/);
  });

  it('uses Arabic-only letters somewhere in the Arabic catalogue (ي ك)', () => {
    const corpus = Object.values(TRANSLATIONS.ar).join(' ');
    expect(corpus).toMatch(/[يك]/);
  });

  it('keeps the shared interpolation placeholders identical across locales', () => {
    for (const key of referenceKeys(TRANSLATIONS.en)) {
      const expected = extractPlaceholders(TRANSLATIONS.en[key] ?? '');
      expect(extractPlaceholders(TRANSLATIONS.ar[key] ?? ''), `ar:${key}`).toEqual(expected);
      expect(extractPlaceholders(TRANSLATIONS.fa[key] ?? ''), `fa:${key}`).toEqual(expected);
    }
  });
});

describe('checkCatalogue', () => {
  it('accepts a complete catalogue', () => {
    expect(checkCatalogue(reference, { ...reference }, 'ar')).toEqual([]);
  });

  it('fails with "missing-key" when a key is absent', () => {
    const partial = { ...reference };
    delete (partial as Record<string, string>)['page.count'];

    const issues = checkCatalogue(reference, partial, 'fa');
    expect(issues).toHaveLength(1);
    expect(issues[0]).toMatchObject({ kind: 'missing-key', key: 'page.count', language: 'fa' });
    expect(describeIssue(issues[0]!)).toBe('[missing-key] missing "page.count" in fa');
  });

  it('fails with "empty-value" for blank or whitespace-only translations', () => {
    const catalogue = { ...reference, 'page.title': '   ' };
    const issues = checkCatalogue(reference, catalogue, 'ar');
    expect(issues).toHaveLength(1);
    expect(issues[0]).toMatchObject({ kind: 'empty-value', key: 'page.title' });
  });

  it('fails with "not-a-string" when a value is an object or a number', () => {
    const catalogue = { ...reference, 'page.title': 42 as unknown as string };
    const issues = checkCatalogue(reference, catalogue, 'ar');
    expect(issues).toHaveLength(1);
    expect(issues[0]).toMatchObject({ kind: 'not-a-string', key: 'page.title' });
  });

  it('fails with "extra-key" for a key the reference does not have', () => {
    const catalogue = { ...reference, 'page.orphan': 'زائد' };
    const issues = checkCatalogue(reference, catalogue, 'ar');
    expect(issues).toHaveLength(1);
    expect(issues[0]).toMatchObject({ kind: 'extra-key', key: 'page.orphan' });
  });

  it('fails with "placeholder-mismatch" when a translation drops {{count}}', () => {
    const catalogue = { ...reference, 'page.count': 'عناصر' };
    const issues = checkCatalogue(reference, catalogue, 'ar');
    expect(issues).toHaveLength(1);
    expect(issues[0]).toMatchObject({ kind: 'placeholder-mismatch', key: 'page.count' });
    expect(issues[0]?.detail).toContain('{{count}}');
  });

  it('fails when a translation invents a placeholder', () => {
    const catalogue = { ...reference, 'page.count': '{{total}} عنصرًا' };
    const issues = checkCatalogue(reference, catalogue, 'ar');
    expect(issues).toHaveLength(1);
    expect(issues[0]?.detail).toContain('{{total}}');
  });

  it('reports every problem at once instead of failing on the first', () => {
    const catalogue = { ...reference, 'page.title': '', 'page.extra': 'x' };
    delete (catalogue as Record<string, string>)['page.greeting'];

    const issues = checkCatalogue(reference, catalogue, 'fa');
    expect(issues.map((issue) => issue.kind).sort()).toEqual(['empty-value', 'extra-key', 'missing-key']);
  });

  it('checks all translated locales and skips the reference locale', () => {
    const catalogues = {
      en: reference,
      ar: { ...reference } as Catalogue,
      fa: { ...reference, 'page.title': '' } as Catalogue,
    };
    const issues = checkAllCatalogues(catalogues, 'en');
    expect(issues).toHaveLength(1);
    expect(issues[0]).toMatchObject({ language: 'fa', kind: 'empty-value' });
  });
});

describe('extractPlaceholders', () => {
  it('returns sorted, deduplicated placeholder names', () => {
    expect(extractPlaceholders('{{count}} of {{total}} at {{count}}')).toEqual(['count', 'total']);
  });

  it('tolerates inner whitespace', () => {
    expect(extractPlaceholders('{{ current }} / {{total}}')).toEqual(['current', 'total']);
  });

  it('returns an empty list for text without placeholders', () => {
    expect(extractPlaceholders('لا شيء')).toEqual([]);
  });
});

describe('language metadata', () => {
  it('marks Arabic and Persian as RTL and English as LTR', () => {
    expect(directionOf('ar')).toBe('rtl');
    expect(directionOf('fa')).toBe('rtl');
    expect(directionOf('en')).toBe('ltr');
    expect(LANGUAGE_META.ar.direction).toBe('rtl');
  });

  it('resolves the initial language from storage, then the browser, then Arabic', () => {
    expect(resolveInitialLanguage('fa')).toBe('fa');
    expect(resolveInitialLanguage(null, ['fa-IR', 'en-US'])).toBe('fa');
    expect(resolveInitialLanguage(undefined, ['de-DE', 'en-GB'])).toBe('en');
    expect(resolveInitialLanguage('klingon', ['de-DE'])).toBe('ar');
    expect(resolveInitialLanguage(null)).toBe('ar');
  });
});
