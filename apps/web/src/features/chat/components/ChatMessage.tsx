import { useTranslation } from 'react-i18next';
import { cn } from '../../../lib/utils';

interface ChatMessageProps {
  role: string;
  content: string;
  /** Renders the live "…" streaming indicator (SPEC §8.3-D). */
  streaming?: boolean;
  testId?: string;
}

/**
 * A single conversation bubble. User messages align to the inline end and
 * assistant messages to the inline start via logical properties (ms-/me-),
 * so Arabic (RTL) mirrors correctly (SPEC §8.2). Content is plain text in
 * this MVP renderer — Markdown sanitization lands with 8.3-D's full renderer.
 */
export function ChatMessage({ role, content, streaming, testId }: ChatMessageProps) {
  const { t } = useTranslation();
  const isUser = role === 'user';

  return (
    <div
      data-testid={testId}
      className={cn('flex flex-col gap-1', isUser ? 'ms-auto items-end' : 'me-auto items-start')}
    >
      <span className="text-xs text-nx-fg-muted">
        {isUser ? t('chat.roles.user') : t('chat.roles.assistant')}
      </span>
      <div
        className={cn(
          'max-w-[85%] whitespace-pre-wrap rounded-nx-lg px-3 py-2 text-sm',
          isUser
            ? 'bg-nx-primary text-nx-primary-fg'
            : 'border border-nx-border bg-nx-surface text-nx-fg',
        )}
      >
        {content}
      </div>
      {streaming && (
        <span
          role="status"
          data-testid="streaming-indicator"
          className="text-xs text-nx-accent"
        >
          {t('chat.streaming')}
        </span>
      )}
    </div>
  );
}
