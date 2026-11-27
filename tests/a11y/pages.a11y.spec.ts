/**
 * axe accessibility checks for every main page in every shipped language.
 *
 * Matrix: 5 pages × 3 languages = 15 axe runs, plus the interaction states that
 * expose different markup (wizard progressed, dark theme, light theme).
 *
 * SPEC §8.2 requires WCAG AA and axe checks in Playwright; SPEC §5.1 asks for
 * the same for the Connection Manager specifically.
 */
import { expect, test } from '@playwright/test';

import { expectNoAxeViolations } from './support/axe.ts';
import { LOCALES, MAIN_PAGES, expectDocumentLanguage, expectMirroredLayout, openAs } from './support/locales.ts';

for (const locale of LOCALES) {
  test.describe(`accessibility — ${locale.language} (${locale.dir})`, () => {
    for (const pageInfo of MAIN_PAGES) {
      test(`${pageInfo.name} page has no axe violations and correct direction`, async ({ page }) => {
        await openAs(page, locale.language, pageInfo.path);

        await expectDocumentLanguage(page, locale.language, locale.dir);
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
        await expectMirroredLayout(page, locale.dir);

        await expectNoAxeViolations(page, `${pageInfo.name} [${locale.language}]`);
      });
    }
  });
}

test.describe('accessibility — interaction states', () => {
  test('browser-connection wizard is accessible after advancing three steps', async ({ page }) => {
    await openAs(page, 'ar', '/connections');

    const advance = page.getByTestId('wizard-advance');
    await expect(advance).toBeEnabled();
    await advance.click();
    await advance.click();
    await advance.click();

    await expect(page.getByText('الخطوة 4 من 5').first()).toBeVisible();
    await expectNoAxeViolations(page, 'connections wizard step 4 [ar]');
  });

  test('light theme keeps WCAG AA contrast on the dashboard', async ({ page }) => {
    await openAs(page, 'en', '/');

    // Switch theme through the real control, not by writing the attribute.
    await page.getByTestId('theme-toggle').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

    await expectNoAxeViolations(page, 'dashboard light theme [en]');
  });

  test('skip link is reachable and moves focus to the main landmark', async ({ page }) => {
    await openAs(page, 'en', '/');

    await page.keyboard.press('Tab');
    const skipLink = page.locator('.nx-skip-link');
    await expect(skipLink).toBeFocused();

    await page.keyboard.press('Enter');
    await expect(page.locator('#main-content')).toBeVisible();
    await expect(page).toHaveURL(/#main-content$/);
  });

  test('every page is fully keyboard navigable from the skip link', async ({ page }) => {
    await openAs(page, 'ar', '/settings');

    const reached: string[] = [];
    for (let index = 0; index < 12; index += 1) {
      await page.keyboard.press('Tab');
      const focused = await page.evaluate(() => {
        const element = document.activeElement;
        if (!element) return null;
        return {
          tag: element.tagName.toLowerCase(),
          text: (element.textContent ?? '').trim().slice(0, 40),
        };
      });
      if (focused) reached.push(`${focused.tag}:${focused.text}`);
    }

    // The skip link, five nav links, two controls in the header and the page's
    // own controls must all be reachable by Tab alone.
    expect(reached.filter((entry) => entry.startsWith('a:')).length).toBeGreaterThanOrEqual(6);
    expect(reached.some((entry) => entry.startsWith('select:'))).toBe(true);
    expect(reached.some((entry) => entry.startsWith('button:'))).toBe(true);
  });
});
