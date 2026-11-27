import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * Vitest configuration for the web workspace.
 *
 * Unit tests run in jsdom and cover the i18n coverage rules, the
 * `<html lang/dir>` sync, locale-aware formatting and the page render smoke
 * tests. Browser-level accessibility checks live in `tests/a11y/` (Playwright +
 * axe) because they need a real layout engine and real fonts.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['src/test/setup.ts'],
    css: false,
    reporters: process.env.CI ? ['default', 'github-actions'] : ['default'],
    restoreMocks: true,
  },
});
