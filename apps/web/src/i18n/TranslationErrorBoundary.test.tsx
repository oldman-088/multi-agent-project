/**
 * The Error Boundary is what stops a missing key (or any render failure in
 * translated content) from blanking the whole product — the exact regression the
 * reviewer found when `throwOnMissingKey` was hard-coded to `true`.
 */
import { act, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { TranslationErrorBoundary } from './TranslationErrorBoundary.tsx';

/** A component that throws during render, like a missing key in dev does. */
function Explodes({ message }: { message: string }): never {
  throw new Error(message);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('TranslationErrorBoundary', () => {
  it('renders its children when nothing throws', () => {
    render(
      <TranslationErrorBoundary language="en">
        <p>safe content</p>
      </TranslationErrorBoundary>,
    );
    expect(screen.getByText('safe content')).toBeInTheDocument();
    expect(screen.queryByTestId('translation-error')).not.toBeInTheDocument();
  });

  it('replaces a crashed subtree with a readable, announced panel (never blank)', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    render(
      <TranslationErrorBoundary language="en">
        <Explodes message='[i18n] missing translation key "nav.dashboard"' />
      </TranslationErrorBoundary>,
    );

    const panel = screen.getByTestId('translation-error');
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveAttribute('role', 'alert');
    // The rest of the page still exists: this is a degraded panel, not a blank screen.
    expect(panel).toHaveTextContent('This section could not be displayed');
    // The panel replaces the page, so it must own the only <h1> on the screen
    // (axe `page-has-heading-one`).
    expect(within(panel).getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(panel).toHaveTextContent('missing translation key');
  });

  it('uses the active language and direction for the fallback copy', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    render(
      <TranslationErrorBoundary language="ar-SA">
        <Explodes message="boom" />
      </TranslationErrorBoundary>,
    );

    const panel = screen.getByTestId('translation-error');
    expect(panel).toHaveAttribute('lang', 'ar');
    expect(panel).toHaveAttribute('dir', 'rtl');
    expect(panel).toHaveTextContent('تعذّر عرض هذا القسم');
  });

  it('falls back to Arabic + RTL for an unknown language tag', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    render(
      <TranslationErrorBoundary language="klingon">
        <Explodes message="boom" />
      </TranslationErrorBoundary>,
    );

    const panel = screen.getByTestId('translation-error');
    expect(panel).toHaveAttribute('lang', 'ar');
    expect(panel).toHaveAttribute('dir', 'rtl');
  });

  it('offers a real retry that re-renders the children', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    let shouldThrow = true;
    function Flaky() {
      if (shouldThrow) throw new Error('transient');
      return <p>recovered</p>;
    }

    render(
      <TranslationErrorBoundary language="en">
        <Flaky />
      </TranslationErrorBoundary>,
    );

    expect(screen.getByTestId('translation-error')).toBeInTheDocument();

    shouldThrow = false;
    act(() => {
      screen.getByRole('button', { name: 'Try again' }).click();
    });

    expect(screen.getByText('recovered')).toBeInTheDocument();
    expect(screen.queryByTestId('translation-error')).not.toBeInTheDocument();
  });

  it('reports through onError when a sink is provided', () => {
    const onError = vi.fn();

    render(
      <TranslationErrorBoundary language="en" onError={onError}>
        <Explodes message="reported" />
      </TranslationErrorBoundary>,
    );

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0]?.[0]).toBeInstanceOf(Error);
  });
});
