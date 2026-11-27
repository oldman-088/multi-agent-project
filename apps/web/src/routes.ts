/**
 * The route table, in one place.
 *
 * `App.tsx` renders it and the a11y/screenshot suites read it, so a new page
 * cannot be added to the app and silently skipped by the accessibility matrix.
 * `src/routes.test.ts` is the guard that keeps the two halves honest.
 */

/** A navigable page in the shell. */
export interface AppRoute {
  /** URL path as React Router matches it. */
  readonly path: string;
  /** Stable file/artifact name used by the screenshot and a11y matrices. */
  readonly name: string;
  /** Translation key of the page's `<h1>`. */
  readonly titleKey: string;
  /** True for the index route (`/`). */
  readonly index?: true;
}

/**
 * The main pages. Every entry must be reachable from the primary navigation and
 * must be rendered by `App.tsx` — `routes.test.ts` asserts both.
 */
export const MAIN_ROUTES = [
  { path: '/', name: 'dashboard', titleKey: 'page.dashboard.title', index: true },
  { path: '/connections', name: 'connections', titleKey: 'connection.title' },
  { path: '/agents', name: 'agents', titleKey: 'page.agents.title' },
  { path: '/runs', name: 'runs', titleKey: 'page.runs.title' },
  { path: '/settings', name: 'settings', titleKey: 'page.settings.title' },
] as const satisfies readonly AppRoute[];

/** Primary navigation, derived from the routes so the two cannot drift. */
export const NAV_ROUTES = [
  { to: '/', labelKey: 'nav.dashboard', end: true },
  { to: '/connections', labelKey: 'nav.connections', end: false },
  { to: '/agents', labelKey: 'nav.agents', end: false },
  { to: '/runs', labelKey: 'nav.runs', end: false },
  { to: '/settings', labelKey: 'nav.settings', end: false },
] as const;

/** Route names, for use as test ids and artifact folder names. */
export const ROUTE_NAMES: readonly string[] = MAIN_ROUTES.map((route) => route.name);
