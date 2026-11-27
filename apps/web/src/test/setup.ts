/**
 * Vitest setup.
 *
 * - jest-dom matchers for the jsdom unit tests;
 * - an explicit `cleanup()` between tests: Testing Library's automatic cleanup
 *   relies on globals being enabled, and this workspace keeps them off so tests
 *   import their helpers explicitly.
 */
import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});
