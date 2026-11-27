import { describe, expect, it } from 'vitest';
import ar from './locales/ar.json';
import en from './locales/en.json';
import fa from './locales/fa.json';

interface LocaleTree {
  [key: string]: string | LocaleTree;
}

function flattenKeys(tree: LocaleTree, prefix = ''): string[] {
  return Object.entries(tree).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') {
      return [path];
    }
    return flattenKeys(value, path);
  });
}

function collectStrings(tree: LocaleTree, prefix = ''): [string, string][] {
  return Object.entries(tree).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') {
      return [[path, value] as [string, string]];
    }
    return collectStrings(value, path);
  });
}

const locales = { ar, en, fa } as const;
const flattened = {
  ar: flattenKeys(ar as LocaleTree),
  en: flattenKeys(en as LocaleTree),
  fa: flattenKeys(fa as LocaleTree),
};

describe('i18n locale key parity (SPEC 8.2 — a test fails if any key is missing)', () => {
  it('ar, en and fa expose exactly the same translation keys', () => {
    expect([...flattened.ar].sort()).toEqual([...flattened.en].sort());
    expect([...flattened.ar].sort()).toEqual([...flattened.fa].sort());
  });

  it('every translation value is a non-empty string', () => {
    for (const [name, tree] of Object.entries(locales)) {
      for (const [key, value] of collectStrings(tree as LocaleTree)) {
        expect(value.trim(), `${name}:${key} must not be empty`).not.toBe('');
      }
    }
  });

  it('interpolation placeholders match across locales', () => {
    const placeholderPattern = /\{\w+\}/g;
    const placeholdersFor = (tree: LocaleTree) =>
      new Map(
        collectStrings(tree).map(([key, value]) => [
          key,
          (value.match(placeholderPattern) ?? []).sort().join(','),
        ]),
      );

    const arPlaceholders = placeholdersFor(ar as LocaleTree);
    const enPlaceholders = placeholdersFor(en as LocaleTree);
    const faPlaceholders = placeholdersFor(fa as LocaleTree);

    expect(Object.fromEntries(enPlaceholders)).toEqual(Object.fromEntries(arPlaceholders));
    expect(Object.fromEntries(faPlaceholders)).toEqual(Object.fromEntries(arPlaceholders));
  });
});
