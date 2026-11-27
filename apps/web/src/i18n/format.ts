/**
 * Locale-aware formatting (SPEC §8.2: "Locale-aware numbers, dates and relative
 * times").
 *
 * Every formatter takes the active language, so switching from Arabic to
 * English changes digits, grouping and date order. These helpers are used by
 * the pages and asserted in the unit tests.
 */

import type { Language } from './languages.ts';

/** BCP-47 tags used for `Intl`; Arabic/Persian get their native numbering. */
const INTL_LOCALES: Readonly<Record<Language, string>> = {
  ar: 'ar-EG',
  en: 'en-US',
  fa: 'fa-IR',
};

/** Format a number with the locale's digits and grouping. */
export function formatNumber(value: number, language: Language): string {
  return new Intl.NumberFormat(INTL_LOCALES[language]).format(value);
}

/** Format a date (day, month, year) with the locale's calendar and digits. */
export function formatDate(value: Date, language: Language): string {
  return new Intl.DateTimeFormat(INTL_LOCALES[language], {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(value);
}

/** Format an amount in a currency for the locale. */
export function formatCurrency(value: number, currency: string, language: Language): string {
  return new Intl.NumberFormat(INTL_LOCALES[language], {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * Relative time ("3 hours ago") via `Intl.RelativeTimeFormat`.
 * `now` is injectable so tests are deterministic.
 */
export function formatRelativeTime(
  value: Date,
  language: Language,
  now: Date = new Date(),
): string {
  const diffSeconds = Math.round((value.getTime() - now.getTime()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(INTL_LOCALES[language], { numeric: 'auto' });

  const thresholds: ReadonlyArray<{ unit: Intl.RelativeTimeFormatUnit; seconds: number }> = [
    { unit: 'second', seconds: 1 },
    { unit: 'minute', seconds: 60 },
    { unit: 'hour', seconds: 3600 },
    { unit: 'day', seconds: 86_400 },
    { unit: 'month', seconds: 2_629_800 },
    { unit: 'year', seconds: 31_557_600 },
  ];

  const absolute = Math.abs(diffSeconds);
  const chosen = [...thresholds].reverse().find((step) => absolute >= step.seconds) ?? thresholds[0]!;

  return formatter.format(Math.round(diffSeconds / chosen.seconds), chosen.unit);
}

/** BCP-47 tag the app feeds to `Intl` for a language. */
export function intlLocale(language: Language): string {
  return INTL_LOCALES[language];
}
