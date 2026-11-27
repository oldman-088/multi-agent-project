import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for the NEXUS AGENT OS core user journey tests.
 *
 * Suite: tests/e2e/spec_journeys.spec.ts
 *
 * The tests run against a locally running frontend + backend stack. The stack
 * must be started separately (for example via the app start script / docker
 * compose) before the tests run. This configuration intentionally does NOT
 * declare a `webServer`, so running the E2E suite locally never starts a server
 * that could interfere with the rest of the package (lint, type-check, unit
 * tests).
 *
 * Environment variables:
 *   PLAYWRIGHT_BASE_URL  frontend origin  (default http://localhost:3000)
 *   API_BASE_URL         backend origin   (default http://localhost:8000)
 *
 * All page navigation uses relative paths (frontend rule: relative /api and
 * /ws URLs, never hard-coded localhost in frontend source).
 */

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: true,

  // Fail a run if someone leaves a `test.only` behind on CI.
  forbidOnly: !!process.env.CI,

  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,

  reporter: process.env.CI ? 'github' : 'list',

  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
    },
  ],

  expect: {
    timeout: 5_000,
  },
});
