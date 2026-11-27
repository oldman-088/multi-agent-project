/**
 * Playwright + axe configuration for the accessibility and RTL/LTR screenshot
 * suites in `tests/a11y/`.
 *
 * What runs:
 *   - `npm run test:a11y`    every spec in this folder (axe + screenshots)
 *   - `npm run screenshots`  only the `@screenshots` project
 *   - `npm run a11y:dist`    same suite against a production build: builds
 *                            `apps/web`, starts `vite preview` on port 4173 and
 *                            points `PLAYWRIGHT_BASE_URL` at it
 *
 * The default target is the Vite dev server (`apps/web`). It is started by
 * `webServer` below, bound to 0.0.0.0 so the same command works locally, in CI
 * and inside a container.
 *
 * Browsers: CI installs Playwright's Chromium with
 * `npx playwright install --with-deps chromium`. Sandboxes without access to
 * Playwright's CDN can point `NEXUS_CHROMIUM_EXECUTABLE` at any compatible
 * Chromium binary and add its shared libraries with `LD_LIBRARY_PATH`; the
 * config then launches that binary instead of the bundled one.
 */
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig, devices } from '@playwright/test';

/** Repository root — Playwright runs `webServer.command` from the config's folder otherwise. */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

const PORT = Number(process.env.NEXUS_WEB_PORT ?? 5173);
/** `a11y:dist` runs against the built bundle behind `vite preview`. */
const PREVIEW = process.env.NEXUS_PREVIEW === '1';
const PREVIEW_PORT = 4173;
/**
 * Where the specs navigate. An explicit `PLAYWRIGHT_BASE_URL` always wins; in
 * preview mode the default must be the preview server, not the dev server, or
 * every test would hit a port nothing is listening on.
 */
const BASE_URL =
  process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${PREVIEW ? PREVIEW_PORT : PORT}`;
const CHROMIUM_EXECUTABLE = process.env.NEXUS_CHROMIUM_EXECUTABLE;

export default defineConfig({
  // Playwright resolves `testDir` relative to this config file, so use the absolute path.
  testDir: resolve(REPO_ROOT, 'tests/a11y'),
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  ...(process.env.CI ? { workers: 2 } : {}),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI
    ? [['github'], ['html', { outputFolder: resolve(REPO_ROOT, 'playwright-report/a11y'), open: 'never' }]]
    : [['list']],
  outputDir: resolve(REPO_ROOT, 'test-results/a11y'),

  use: {
    baseURL: BASE_URL,
    locale: 'ar',
    colorScheme: 'dark',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: CHROMIUM_EXECUTABLE
      ? { executablePath: CHROMIUM_EXECUTABLE, args: ['--no-sandbox', '--disable-dev-shm-usage'] }
      : {},
  },

  projects: [
    {
      name: 'a11y',
      testMatch: /.*\.a11y\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'screenshots',
      testMatch: /.*\.screenshots\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],

  // Spread instead of `webServer: undefined`: with `exactOptionalPropertyTypes`
  // the property must be absent, not present-and-undefined.
  ...(PREVIEW
    ? {
        webServer: {
          command: `npm run preview --workspace apps/web -- --port ${PREVIEW_PORT} --strictPort`,
          cwd: REPO_ROOT,
          url: `http://127.0.0.1:${PREVIEW_PORT}`,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      }
    : !process.env.PLAYWRIGHT_BASE_URL && {
        webServer: {
          command: `npm run dev --workspace apps/web -- --port ${PORT} --strictPort`,
          cwd: REPO_ROOT,
          url: BASE_URL,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
          env: { BROWSER: 'none' },
        },
      }),
});
