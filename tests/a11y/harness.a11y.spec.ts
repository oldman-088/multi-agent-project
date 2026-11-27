/**
 * Negative controls for the axe harness.
 *
 * An accessibility suite that cannot fail is worse than none: these tests feed
 * `expectNoAxeViolations` deliberately broken markup and require it to report
 * the expected violations. They are the proof that the green results in
 * `pages.a11y.spec.ts` mean something.
 *
 * They do not touch the app at all — `page.setContent` renders standalone
 * fragments, so a regression in the app can never make them pass or fail by
 * accident. `file:` URLs and network access are not used.
 */
import { expect, test } from '@playwright/test';

import { expectNoAxeViolations } from './support/axe.ts';

test.describe('axe harness negative controls', () => {
  test('detects an image without alternative text', async ({ page }) => {
    await page.setContent('<main><h1>Report</h1><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw="></main>');

    await expect(expectNoAxeViolations(page, 'negative control: missing alt')).rejects.toThrow(/image-alt/);
  });

  test('detects low-contrast text', async ({ page }) => {
    await page.setContent(`
      <style>
        body { background: #ffffff; }
        h1 { color: #cfcfcf; font-size: 12px; }
      </style>
      <main><h1>Faint heading</h1><p style="color:#d0d0d0;font-size:12px">Barely visible paragraph</p></main>
    `);

    await expect(expectNoAxeViolations(page, 'negative control: contrast')).rejects.toThrow(/color-contrast/);
  });

  test('detects a button without an accessible name', async ({ page }) => {
    await page.setContent('<main><h1>Actions</h1><button type="button"></button></main>');

    await expect(expectNoAxeViolations(page, 'negative control: unnamed button')).rejects.toThrow(
      /button-name|label/,
    );
  });

  test('detects a missing document language', async ({ page }) => {
    await page.setContent('<main><h1>No lang attribute</h1></main>');
    await page.evaluate(() => document.documentElement.removeAttribute('lang'));

    await expect(expectNoAxeViolations(page, 'negative control: html-lang')).rejects.toThrow(/html-has-lang/);
  });

  test('passes a fragment that is accessible', async ({ page }) => {
    await page.setContent(`
      <html lang="ar" dir="rtl">
        <head><title>نظيف</title></head>
        <body style="background:#0b1020;color:#e8eefc">
          <main>
            <h1>نظيف</h1>
            <button type="button">حفظ</button>
          </main>
        </body>
      </html>
    `);

    await expectNoAxeViolations(page, 'negative control: clean fragment');
  });
});
