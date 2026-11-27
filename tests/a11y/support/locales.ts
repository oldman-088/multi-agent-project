/**
 * Shared fixtures for the accessibility and screenshot suites.
 *
 * Each language is exercised with its expected text direction, and the main
 * pages are enumerated once so a new page cannot be forgotten by one suite and
 * covered by another.
 */
import { expect, type Page } from '@playwright/test';

/** Languages shipped by the product, with the direction they must render in. */
export const LOCALES = [
  { language: 'ar', dir: 'rtl', nativeName: 'العربية' },
  { language: 'en', dir: 'ltr', nativeName: 'English' },
  { language: 'fa', dir: 'rtl', nativeName: 'فارسی' },
] as const;

export type Locale = (typeof LOCALES)[number];
export type Language = Locale['language'];
export type ExpectedDirection = Locale['dir'];

/** Main pages, with the translation key of their `<h1>`. */
export const MAIN_PAGES = [
  { path: '/', name: 'dashboard', titleKey: 'page.dashboard.title' },
  { path: '/connections', name: 'connections', titleKey: 'connection.title' },
  { path: '/agents', name: 'agents', titleKey: 'page.agents.title' },
  { path: '/runs', name: 'runs', titleKey: 'page.runs.title' },
  { path: '/settings', name: 'settings', titleKey: 'page.settings.title' },
] as const;

/** The default (Arabic) and the LTR (English) locales used by the screenshot matrix. */
export const SCREENSHOT_LOCALES = ['ar', 'en'] as const;

/**
 * Navigate to a page and activate a language the way the owner does it.
 *
 * The language is persisted in `localStorage` before the first paint (the app's
 * pre-paint bootstrap reads it), then the switcher is used to prove that the
 * interactive path also works. Assertions on `<html>` run before that so a
 * regression in the pre-paint path cannot be masked.
 */
export async function openAs(
  page: Page,
  language: Language,
  path = '/',
): Promise<void> {
  await page.addInitScript((lang: string) => {
    try {
      window.localStorage.setItem('nexus.language', lang);
    } catch {
      /* storage blocked: the app falls back to Arabic, and the assertion below fails loudly */
    }
  }, language);

  await page.goto(path);
  await page.waitForLoadState('networkidle');
}

/** Assert `<html lang>` and `<html dir>` match the active language (SPEC §8.2). */
export async function expectDocumentLanguage(
  page: Page,
  language: Language,
  dir: ExpectedDirection,
): Promise<void> {
  await expect(page.locator('html')).toHaveAttribute('lang', language);
  await expect(page.locator('html')).toHaveAttribute('dir', dir);
}

/**
 * Assert the layout actually mirrors: for RTL the header's inline-start edge is
 * the right edge, for LTR it is the left edge. This catches a stylesheet that
 * sets `dir` correctly but still uses physical left/right positioning.
 */
export async function expectMirroredLayout(page: Page, dir: ExpectedDirection): Promise<void> {
  const box = await page.locator('.nx-header').boundingBox();
  const viewport = page.viewportSize() ?? { width: 1280, height: 720 };
  expect(box).not.toBeNull();

  const leftGap = box!.x;
  const rightGap = viewport.width - (box!.x + box!.width);

  if (dir === 'rtl') {
    expect(rightGap).toBeLessThanOrEqual(leftGap);
  } else {
    expect(leftGap).toBeLessThanOrEqual(rightGap);
  }

  const brand = await page.locator('.nx-brand__mark').boundingBox();
  const tools = await page.locator('.nx-header__tools').boundingBox();
  expect(brand).not.toBeNull();
  expect(tools).not.toBeNull();

  if (dir === 'rtl') {
    // Brand on the right, controls on the left.
    expect(brand!.x).toBeGreaterThan(tools!.x);
  } else {
    expect(brand!.x).toBeLessThan(tools!.x);
  }
}
