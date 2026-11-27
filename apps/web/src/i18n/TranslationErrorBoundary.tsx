/**
 * Error boundary around translated content.
 *
 * A missing translation key is a bug, but it must never blank the product. In a
 * development build `createI18n()` throws from `missingKeyHandler`, and any
 * other render error in translated content would unmount the whole React tree
 * without a boundary. This boundary catches both and shows a readable fallback
 * in the active language, with a real "retry" action.
 *
 * The fallback text is intentionally **not** translated through i18next: if the
 * translation layer itself is what failed, calling it again from the fallback
 * would throw a second time. It uses the same three static strings the
 * catalogues ship, selected directly.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react';

import { DEFAULT_LANGUAGE, isLanguage, type Language } from './languages.ts';

/** Statically selected fallback copy; deliberately bypasses i18next. */
const FALLBACK_COPY: Readonly<Record<Language, { title: string; body: string; retry: string }>> = {
  ar: {
    title: 'تعذّر عرض هذا القسم',
    body: 'حدث خطأ في النصوص أو في العرض. بقية الواجهة ما زالت تعمل.',
    retry: 'أعد المحاولة',
  },
  en: {
    title: 'This section could not be displayed',
    body: 'A text or rendering error occurred. The rest of the interface still works.',
    retry: 'Try again',
  },
  fa: {
    title: 'نمایش این بخش ممکن نشد',
    body: 'خطایی در متن یا نمایش رخ داد. بقیهٔ رابط کاربری هنوز کار می‌کند.',
    retry: 'تلاش دوباره',
  },
};

/** Props of {@link TranslationErrorBoundary}. */
export interface TranslationErrorBoundaryProps {
  readonly children: ReactNode;
  /** Active language for the fallback copy. */
  readonly language?: string;
  /** Optional sink for reporting; defaults to `console.error`. */
  readonly onError?: (error: Error, info: ErrorInfo) => void;
}

interface State {
  readonly error: Error | null;
}

export class TranslationErrorBoundary extends Component<TranslationErrorBoundaryProps, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    if (this.props.onError) {
      this.props.onError(error, info);
      return;
    }
    // eslint-disable-next-line no-console -- the only place a render failure is surfaced
    console.error('[i18n] render failed inside translated content', error, info.componentStack);
  }

  private readonly reset = (): void => {
    this.setState({ error: null });
  };

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    const base = typeof this.props.language === 'string' ? this.props.language.split('-')[0] : DEFAULT_LANGUAGE;
    const copy = FALLBACK_COPY[isLanguage(base) ? base : DEFAULT_LANGUAGE];
    const dir = base === 'en' ? 'ltr' : 'rtl';

    return (
      <section
        className="nx-empty"
        role="alert"
        aria-live="assertive"
        dir={dir}
        lang={isLanguage(base) ? base : DEFAULT_LANGUAGE}
        data-testid="translation-error"
      >
        {/* `<h1>`: the panel replaces the page content, so it becomes the
            page heading. Using `h2` left the document without a level-one
            heading, which axe reports as `page-has-heading-one`. */}
        <h1 className="nx-card__title">{copy.title}</h1>
        <p className="nx-muted">{copy.body}</p>
        <p className="nx-faint nx-mono" dir="ltr">
          {error.message}
        </p>
        <button type="button" className="nx-button" onClick={this.reset}>
          {copy.retry}
        </button>
      </section>
    );
  }
}
