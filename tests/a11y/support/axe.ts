/**
 * axe-core helpers shared by the accessibility specs.
 *
 * Rules are pinned explicitly (rather than relying on axe defaults) so a
 * deliberate exception is visible in code review:
 *   - `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa` — SPEC §8.2 asks
 *     for WCAG AA;
 *   - `best-practice` is included because it catches landmark/heading errors.
 *
 * `color-contrast` needs real layouts and computed styles, which is why these
 * checks live in Playwright and not in jsdom.
 */
import AxeBuilder from '@axe-core/playwright';
import { expect, type Page } from '@playwright/test';

/** The axe rules the suite enforces. */
export const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] as const;

/** A single axe violation reduced to the fields a report needs. */
export interface AxeSummary {
  readonly id: string;
  readonly impact: string | null;
  readonly help: string;
  readonly nodes: readonly string[];
}

/**
 * Run axe against the current page and fail with a readable report.
 * Returns the summaries so a spec can assert on the count as well.
 */
export async function expectNoAxeViolations(
  page: Page,
  context: string,
  rules: { disabled?: readonly string[] } = {},
): Promise<AxeSummary[]> {
  const builder = new AxeBuilder({ page }).withTags([...AXE_TAGS]);
  if (rules.disabled && rules.disabled.length > 0) {
    builder.disableRules([...rules.disabled]);
  }

  const { violations } = await builder.analyze();

  const summary: AxeSummary[] = violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact ?? null,
    help: violation.help,
    nodes: violation.nodes.map((node) => node.target.join(' ')),
  }));

  expect(
    summary,
    `${context}: axe reported ${summary.length} violation(s)\n` +
      summary.map((item) => `  - ${item.id} (${item.impact}): ${item.help} → ${item.nodes.join(', ')}`).join('\n'),
  ).toEqual([]);

  return summary;
}
