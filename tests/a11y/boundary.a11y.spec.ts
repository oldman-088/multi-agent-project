/**
 * The Error Boundary, verified in a real browser.
 *
 * The reviewer's finding was that a missing key in a production build threw
 * during render with no boundary, leaving a blank screen. `App.tsx` wraps every
 * page in `TranslationErrorBoundary`, so this spec forces a genuine
 * *render-time* failure in the real app and asserts:
 *
 *   1. the boundary's panel appears (the page is not blank),
 *   2. the app shell survives (skip link, navigation, main landmark), so the
 *      failure degrades instead of destroying the product,
 *   3. the degraded state is still accessible.
 *
 * The failure is injected without mocking any component: the dashboard formats
 * numbers during render via `Intl.NumberFormat`, so making that constructor
 * throw produces a real render error in real product code.
 */
import { expect, test } from '@playwright/test';

import { expectNoAxeViolations } from './support/axe.ts';
import { expectDocumentLanguage, openAs } from './support/locales.ts';

test.describe('translation error boundary', () => {
  test('a render failure degrades to an accessible panel inside the surviving shell', async ({ page }) => {
    await page.addInitScript(() => {
      // Runs before the bundle: the next Intl.NumberFormat construction throws,
      // which happens inside DashboardPage's render body.
      // Throw on *every* call, not just the first: React 19 recovers from a
      // concurrent-render error by retrying synchronously, so a one-shot failure
      // never reaches the boundary. A persistent failure is what a real
      // broken-data render looks like, and only the boundary can stop it.
      // @ts-expect-error -- deliberately replacing a constructor
      Intl.NumberFormat = function patched() {
        throw new Error('forced render failure for the error-boundary test');
      };
    });

    await openAs(page, 'en', '/');

    // The boundary must catch the render error and show its panel.
    const panel = page.getByTestId('translation-error');
    await expect(panel).toBeVisible();
    await expect(panel).toHaveAttribute('role', 'alert');
    await expect(panel).toHaveAttribute('lang', 'en');
    await expect(panel).toContainText('This section could not be displayed');
    await expect(panel).toContainText('forced render failure');
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();

    // …and because the boundary sits inside the shell, the chrome survives.
    await expect(page.locator('.nx-app')).toBeVisible();
    await expect(page.locator('.nx-skip-link')).toHaveCount(1);
    await expect(page.getByRole('navigation')).toBeVisible();
    await expect(page.locator('#main-content')).toBeVisible();
    // The document language is untouched by the crash.
    await expectDocumentLanguage(page, 'en', 'ltr');

    // A degraded state users can still read must also be accessible.
    await expectNoAxeViolations(page, 'error-boundary panel [en]');
  });

  test('the panel is right-to-left and in Arabic when Arabic is active', async ({ page }) => {
    await page.addInitScript(() => {
      // @ts-expect-error -- deliberately replacing a constructor
      Intl.NumberFormat = function patched() {
        throw new Error('forced render failure');
      };
    });

    await openAs(page, 'ar', '/');
    await expectDocumentLanguage(page, 'ar', 'rtl');

    const panel = page.getByTestId('translation-error');
    await expect(panel).toBeVisible();
    await expect(panel).toHaveAttribute('lang', 'ar');
    await expect(panel).toHaveAttribute('dir', 'rtl');
    await expect(panel).toContainText('تعذّر عرض هذا القسم');

    await expectNoAxeViolations(page, 'error-boundary panel [ar]');
  });
});
