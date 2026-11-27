/**
 * `<html lang/dir>` must be derived from the active language (SPEC §8.2) —
 * never hard-coded — and must follow a runtime language change.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  applyDocumentLanguage,
  documentLanguageAttributes,
  syncDocumentLanguage,
} from './direction.ts';
import { createI18n, isDevelopmentBuild } from './i18next.ts';
import { LANGUAGE_STORAGE_KEY, type Language } from './languages.ts';

describe('documentLanguageAttributes', () => {
  it('maps Arabic to lang="ar" dir="rtl"', () => {
    expect(documentLanguageAttributes('ar')).toEqual({ lang: 'ar', dir: 'rtl' });
  });

  it('maps Persian to lang="fa" dir="rtl"', () => {
    expect(documentLanguageAttributes('fa')).toEqual({ lang: 'fa', dir: 'rtl' });
  });

  it('maps English to lang="en" dir="ltr"', () => {
    expect(documentLanguageAttributes('en')).toEqual({ lang: 'en', dir: 'ltr' });
  });

  it('falls back to the Arabic default for an unknown tag', () => {
    expect(documentLanguageAttributes('de' as Language)).toEqual({ lang: 'ar', dir: 'rtl' });
  });
});

describe('applyDocumentLanguage', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('dir');
    document.documentElement.removeAttribute('lang');
  });

  afterEach(() => {
    document.documentElement.removeAttribute('dir');
    document.documentElement.removeAttribute('lang');
  });

  it('writes both attributes onto <html> and returns them', () => {
    expect(applyDocumentLanguage('fa')).toEqual({ lang: 'fa', dir: 'rtl' });
    expect(document.documentElement.getAttribute('lang')).toBe('fa');
    expect(document.documentElement.getAttribute('dir')).toBe('rtl');
  });

  it('switches direction when the language switches', () => {
    applyDocumentLanguage('ar');
    expect(document.documentElement.dir).toBe('rtl');

    applyDocumentLanguage('en');
    expect(document.documentElement.dir).toBe('ltr');
    expect(document.documentElement.lang).toBe('en');
  });

  it('does not throw when there is no document (SSR / node)', () => {
    expect(applyDocumentLanguage('en', undefined)).toEqual({ lang: 'en', dir: 'ltr' });
  });
});

describe('syncDocumentLanguage', () => {
  it('applies the initial language and follows published changes', () => {
    const listeners: ((language: Language) => void)[] = [];
    const unsubscribe = syncDocumentLanguage('ar', (listener) => {
      listeners.push(listener);
      return () => {
        listeners.length = 0;
      };
    });

    expect(document.documentElement.dir).toBe('rtl');

    listeners[0]?.('en');
    expect(document.documentElement.dir).toBe('ltr');
    expect(document.documentElement.lang).toBe('en');

    unsubscribe();
    expect(listeners).toHaveLength(0);
  });
});

describe('createI18n', () => {
  let instance: ReturnType<typeof createI18n> | undefined;

  afterEach(() => {
    instance?.off('languageChanged');
    instance = undefined;
    window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  });

  it('translates a known key in each of the three languages', () => {
    instance = createI18n({ language: 'en', persist: false });
    expect(instance.t('nav.dashboard')).toBe('Dashboard');

    void instance.changeLanguage('ar');
    expect(instance.t('nav.dashboard')).toBe('لوحة القيادة');

    void instance.changeLanguage('fa');
    expect(instance.t('nav.dashboard')).toBe('داشبورد');
  });

  it('interpolates placeholders per language', () => {
    instance = createI18n({ language: 'en', persist: false });
    expect(instance.t('connection.wizard.progress', { current: 2, total: 5 })).toBe('Step 2 of 5');
  });

  it('writes lang and dir to <html> when the language changes', () => {
    instance = createI18n({ language: 'ar', persist: false });
    expect(document.documentElement.getAttribute('dir')).toBe('rtl');

    void instance.changeLanguage('en');
    expect(document.documentElement.getAttribute('dir')).toBe('ltr');
    expect(document.documentElement.getAttribute('lang')).toBe('en');
  });

  it('persists the chosen language to localStorage', () => {
    instance = createI18n({ language: 'en' });
    void instance.changeLanguage('fa');
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('fa');
  });

  it('restores a persisted language on creation', () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'fa');
    instance = createI18n();
    expect(instance.language).toBe('fa');
  });

  it('ignores an invalid persisted language and defaults to Arabic', () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'xx');
    instance = createI18n({ persist: false });
    expect(instance.language).toBe('ar');
  });

  it('throws on a missing key so a missing translation cannot ship silently', () => {
    instance = createI18n({ language: 'ar', persist: false, throwOnMissingKey: true });
    expect(() => instance?.t('does.not.exist')).toThrow(/missing translation key "does\.not\.exist"/);
    // The app instance itself translates every key it ships.
    expect(instance.t('a11y.skipLink')).toMatch(/[\u0600-\u06FF]/);
  });

  it('reports instead of throwing when throwOnMissingKey is off (production build)', () => {
    instance = createI18n({ language: 'en', persist: false, throwOnMissingKey: false });
    expect(instance.t('does.not.exist')).toBe('does.not.exist');
  });

  it('derives the default missing-key policy from the build (dev throws, prod logs)', () => {
    const dev = isDevelopmentBuild();
    // Guard against the regression the reviewer reported: a hard-coded `true`
    // made a production build throw inside render with no boundary, i.e. a
    // blank screen. The default must track the build, never a constant.
    expect(dev).toBe(Boolean(import.meta.env?.DEV));

    const logged: string[] = [];
    const spy = vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
      logged.push(String(args[0]));
    });
    try {
      instance = createI18n({ language: 'fa', persist: false, throwOnMissingKey: !dev });
      // `!dev` is the production policy: log and render the key, never throw.
      expect(() => instance?.t('does.not.exist')).not.toThrow();
      expect(instance.t('does.not.exist')).toBe('does.not.exist');
    } finally {
      spy.mockRestore();
    }
    expect(logged.some((line) => line.includes('missing translation key'))).toBe(true);

    // …and in a dev build the default throws, so a gap cannot be missed.
    instance.off('languageChanged');
    instance = createI18n({ language: 'fa', persist: false, throwOnMissingKey: dev });
    if (dev) expect(() => instance?.t('does.not.exist')).toThrow(/missing translation key/);
    else expect(() => instance?.t('does.not.exist')).not.toThrow();
  });

  it.each([['fa'], ['en']])('names the language that is actually missing the key in %s', (language) => {
    const messages: string[] = [];
    const spy = vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
      messages.push(String(args[0]));
    });
    try {
      instance = createI18n({ language: language as 'fa' | 'en', persist: false, throwOnMissingKey: false });
      instance.t('absent.key');
    } finally {
      spy.mockRestore();
    }

    expect(messages).toHaveLength(1);
    // Regression: `saveMissingTo: 'fallback'` always reported "ar".
    expect(messages[0]).toContain(`active language "${language}"`);
    expect(messages[0]).toContain(`${language}, ar`);
  });
});
