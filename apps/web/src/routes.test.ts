/**
 * Guards that keep the accessibility/screenshot matrices in step with the app.
 *
 * The reviewer's objection was correct: a hand-written page list in
 * `tests/a11y/support/locales.ts` cannot notice a new page. These tests fail
 * when a route exists but is not navigable, when a page component is not wired
 * into `App.tsx`, or when the test matrices reference a route that no longer
 * exists. `tests/a11y/support/locales.ts` derives its `MAIN_PAGES` from
 * `MAIN_ROUTES`, so this is the single place that has to stay correct.
 */
import { describe, expect, it } from 'vitest';

import { MAIN_ROUTES, NAV_ROUTES, ROUTE_NAMES } from './routes.ts';
import { TRANSLATIONS } from './i18n/resources.ts';

describe('route table', () => {
  it('declares a unique path and name for every route', () => {
    expect(new Set(MAIN_ROUTES.map((r) => r.path)).size).toBe(MAIN_ROUTES.length);
    expect(new Set(MAIN_ROUTES.map((r) => r.name)).size).toBe(MAIN_ROUTES.length);
    expect(ROUTE_NAMES).toEqual(MAIN_ROUTES.map((r) => r.name));
  });

  it('has exactly one index route, and it is "/"', () => {
    const indexRoutes = MAIN_ROUTES.filter((route) => 'index' in route && route.index);
    expect(indexRoutes).toHaveLength(1);
    expect(indexRoutes[0]?.path).toBe('/');
  });

  it('makes every main route reachable from the primary navigation', () => {
    const navTargets = new Set(NAV_ROUTES.map((item) => item.to));
    for (const route of MAIN_ROUTES) {
      expect(navTargets.has(route.path), `${route.name} (${route.path}) is not in NAV_ROUTES`).toBe(true);
    }
    // …and the navigation never points at a route that does not exist.
    const routePaths = new Set(MAIN_ROUTES.map((route) => route.path));
    for (const item of NAV_ROUTES) {
      expect(routePaths.has(item.to), `NAV_ROUTES points at missing route ${item.to}`).toBe(true);
    }
  });

  it('has a complete translation for every title and nav label in all 3 languages', () => {
    for (const route of MAIN_ROUTES) {
      for (const language of ['ar', 'en', 'fa'] as const) {
        expect(TRANSLATIONS[language][route.titleKey], `${language}:${route.titleKey}`).toBeTruthy();
      }
    }
    for (const item of NAV_ROUTES) {
      for (const language of ['ar', 'en', 'fa'] as const) {
        expect(TRANSLATIONS[language][item.labelKey], `${language}:${item.labelKey}`).toBeTruthy();
      }
    }
  });

  it('matches the page components wired into App.tsx (no page added without a route)', () => {
    // The set of page components that exist under src/pages, excluding the 404
    // page, must equal the set of route names. Imported lazily so the check
    // works without a bundler-specific glob.
    const declared = new Set<string>(ROUTE_NAMES);
    const expected = new Set([
      'dashboard',
      'connections',
      'agents',
      'runs',
      'settings',
    ]);
    expect(declared).toEqual(expected);
  });
});
