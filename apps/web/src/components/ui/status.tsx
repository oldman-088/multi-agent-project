import { useTranslation } from 'react-i18next';
import { Button } from './button';
import { cn } from '../../lib/utils';

/** Shared screen/region states — SPEC §8.1: loading, empty (with the next
 * action) and error (with retry) are explicit everywhere. */

export function LoadingState({ label, className }: { label?: string; className?: string }) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn('flex flex-col gap-3 p-4', className)}
    >
      <span className="text-sm text-nx-fg-muted">{label ?? t('states.loading')}</span>
      <div className="flex flex-col gap-2" aria-hidden="true">
        <div className="h-10 animate-pulse rounded-nx-md bg-nx-surface-raised" />
        <div className="h-10 animate-pulse rounded-nx-md bg-nx-surface-raised" />
        <div className="h-10 animate-pulse rounded-nx-md bg-nx-surface-raised" />
      </div>
    </div>
  );
}

export interface EmptyStateProps {
  title: string;
  description?: string;
  /** The next action to offer from the empty state. */
  action?: { label: string; onClick: () => void; testId?: string };
  className?: string;
}

export function EmptyState({ title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-start gap-2 p-6', className)}>
      <p className="text-sm font-medium text-nx-fg">{title}</p>
      {description && <p className="text-sm text-nx-fg-muted">{description}</p>}
      {action && (
        <Button size="sm" onClick={action.onClick} data-testid={action.testId}>
          {action.label}
        </Button>
      )}
    </div>
  );
}

export interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({ title, message, onRetry, className }: ErrorStateProps) {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-start gap-2 rounded-nx-md border border-nx-danger p-4',
        className,
      )}
    >
      <p className="text-sm font-medium text-nx-fg">{title ?? t('states.errorTitle')}</p>
      <p className="text-sm text-nx-fg-muted">{message}</p>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry} data-testid="retry-button">
          {t('states.retry')}
        </Button>
      )}
    </div>
  );
}
