/**
 * Locale-aware formatting (SPEC §8.2): digits, date order and currency follow
 * the active language, not the browser default.
 */
import { describe, expect, it } from 'vitest';

import { formatCurrency, formatDate, formatNumber, formatRelativeTime, intlLocale } from './format.ts';

const DATE = new Date('2026-11-27T00:00:00Z');

describe('intlLocale', () => {
  it('maps each language to its Intl tag', () => {
    expect(intlLocale('ar')).toBe('ar-EG');
    expect(intlLocale('en')).toBe('en-US');
    expect(intlLocale('fa')).toBe('fa-IR');
  });
});

describe('formatNumber', () => {
  it('uses Latin digits and a comma grouping for English', () => {
    expect(formatNumber(1_234_567.89, 'en')).toBe('1,234,567.89');
  });

  it('uses Arabic-Indic digits for Arabic', () => {
    expect(formatNumber(1_234_567, 'ar')).toMatch(/[\u0660-\u0669]/);
  });

  it('uses Persian digits for Persian', () => {
    expect(formatNumber(1234, 'fa')).toMatch(/[\u06F0-\u06F9]/);
  });

  it('produces different output per language', () => {
    const outputs = new Set([formatNumber(1234.5, 'en'), formatNumber(1234.5, 'ar'), formatNumber(1234.5, 'fa')]);
    expect(outputs.size).toBe(3);
  });
});

describe('formatDate', () => {
  it('formats the same instant differently per language', () => {
    const english = formatDate(DATE, 'en');
    const arabic = formatDate(DATE, 'ar');
    const persian = formatDate(DATE, 'fa');

    expect(english).toContain('2026');
    expect(english).toContain('November');
    expect(arabic).not.toBe(english);
    expect(persian).not.toBe(english);
    expect(arabic).toMatch(/[\u0600-\u06FF]/);
  });
});

describe('formatCurrency', () => {
  it('keeps the currency code and localises the number', () => {
    expect(formatCurrency(12.5, 'USD', 'en')).toContain('$');
    const arabic = formatCurrency(12.5, 'USD', 'ar');
    expect(arabic).toMatch(/[\u0660-\u0669]/);
  });
});

describe('formatRelativeTime', () => {
  it('returns a past phrase in each language', () => {
    const now = new Date('2026-11-27T12:00:00Z');
    const earlier = new Date('2026-11-27T09:00:00Z');

    expect(formatRelativeTime(earlier, 'en', now)).toMatch(/3 hours ago/);
    expect(formatRelativeTime(earlier, 'ar', now)).toMatch(/[\u0600-\u06FF]/);
    expect(formatRelativeTime(earlier, 'fa', now)).toMatch(/[\u0600-\u06FF]/);
  });
});
