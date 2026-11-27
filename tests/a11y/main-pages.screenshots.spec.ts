/**
 * RTL and LTR screenshots of the main pages (SPEC §8.2: "Playwright takes RTL
 * and LTR screenshots of every main page"; SPEC Phase 1: "Playwright screenshot
 * of the Connection Manager in Arabic and in English").
 *
 * The matrix is Arabic (RTL) + English (LTR) × the five main pages, plus a
 * Persian (RTL) Connection Manager shot because Persian digits and letters
 * (پ چ ژ گ) are a distinct shaping path. Images land in
 * `docs/screenshots/a11y/` where reviewers and `docs/UI_GUIDE.md` can see them.
 *
 * Every screenshot is preceded by assertions, so an image can never silently
 * capture a broken page: the `<html dir/lang>`, the page heading and the mirrored
 * header layout are all verified first.
 */
import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { test } from '@playwright/test';

import {
  MAIN_PAGES,
  SCREENSHOT_LOCALES,
  expectDocumentLanguage,
  expectMirroredLayout,
  openAs,
  type Language,
} from './support/locales.ts';

const here = dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = resolve(here, '../../docs/screenshots/a11y');

/** Directory name of a language inside the screenshot folder. */
function localeFolder(language: Language): string {
  return language === 'ar' ? 'ar-rtl' : 'en-ltr';
}

test.beforeAll(async () => {
  await mkdir(OUTPUT_DIR, { recursive: true });
});

for (const language of SCREENSHOT_LOCALES) {
  const dir = language === 'ar' ? 'rtl' : 'ltr';

  test.describe(`@screenshots ${language} (${dir})`, () => {
    for (const pageInfo of MAIN_PAGES) {
      test(`${pageInfo.name} page — ${language} ${dir}`, async ({ page }) => {
        await openAs(page, language, pageInfo.path);
        await expectDocumentLanguage(page, language, dir);
        await expectMirroredLayout(page, dir);

        await page.screenshot({
          path: resolve(OUTPUT_DIR, localeFolder(language), `${pageInfo.name}.png`),
          fullPage: true,
          animations: 'disabled',
        });
      });
    }
  });
}

test.describe('@screenshots fa (rtl)', () => {
  test('connections page — fa rtl', async ({ page }) => {
    await openAs(page, 'fa', '/connections');
    await expectDocumentLanguage(page, 'fa', 'rtl');
    await expectMirroredLayout(page, 'rtl');

    await page.screenshot({
      path: resolve(OUTPUT_DIR, 'fa-rtl', 'connections.png'),
      fullPage: true,
      animations: 'disabled',
    });
  });
});
