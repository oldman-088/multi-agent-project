import { describe, expect, it } from 'vitest';
import {
  applyDocumentLanguage,
  DEFAULT_LANGUAGE,
  isLanguage,
  isRtlLanguage,
  RTL_LANGUAGES,
  SUPPORTED_LANGUAGES,
} from './direction';

describe('language helpers (SPEC 8.2)', () => {
  it('supports exactly ar, en and fa with Arabic as default', () => {
    expect([...SUPPORTED_LANGUAGES]).toEqual(['ar', 'en', 'fa']);
    expect(DEFAULT_LANGUAGE).toBe('ar');
    expect([...RTL_LANGUAGES].sort()).toEqual(['ar', 'fa']);
  });

  it('isLanguage accepts only supported codes', () => {
    expect(isLanguage('ar')).toBe(true);
    expect(isLanguage('en')).toBe(true);
    expect(isLanguage('fa')).toBe(true);
    expect(isLanguage('de')).toBe(false);
    expect(isLanguage(undefined)).toBe(false);
    expect(isLanguage(null)).toBe(false);
  });

  it('isRtlLanguage is true for ar and fa only', () => {
    expect(isRtlLanguage('ar')).toBe(true);
    expect(isRtlLanguage('fa')).toBe(true);
    expect(isRtlLanguage('en')).toBe(false);
  });
});

describe('applyDocumentLanguage sets <html lang> and <html dir>', () => {
  it('Arabic renders rtl', () => {
    applyDocumentLanguage('ar');
    expect(document.documentElement.lang).toBe('ar');
    expect(document.documentElement.dir).toBe('rtl');
  });

  it('English renders ltr', () => {
    applyDocumentLanguage('en');
    expect(document.documentElement.lang).toBe('en');
    expect(document.documentElement.dir).toBe('ltr');
  });

  it('Persian renders rtl', () => {
    applyDocumentLanguage('fa');
    expect(document.documentElement.lang).toBe('fa');
    expect(document.documentElement.dir).toBe('rtl');
  });

  it('unknown languages fall back to the Arabic default', () => {
    applyDocumentLanguage('xx');
    expect(document.documentElement.lang).toBe('ar');
    expect(document.documentElement.dir).toBe('rtl');
  });
});
