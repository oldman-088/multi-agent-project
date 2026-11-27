import { useTranslation } from 'react-i18next';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../lib/utils';
import type { ApprovalView, ToolCallView } from '../event-stream';

interface ToolCallCardProps {
  toolCall: ToolCallView;
  /** Pending approval tied to this tool call, if any. */
  approval: ApprovalView | null;
  onDecide?: (approval: ApprovalView, approve: boolean) => void;
  deciding?: boolean;
}

const STATUS_LABEL: Record<ToolCallView['status'], string> = {
  running: 'chat.tools.running',
  awaiting_approval: 'chat.tools.awaiting',
  completed: 'chat.tools.completed',
  failed: 'chat.tools.failed',
};

/** One tool-renderer card: status, duration, result and the inline approval
 * card (SPEC §8.3-D). Collapsible details; logical spacing only. */
export function ToolCallCard({ toolCall, approval, onDecide, deciding }: ToolCallCardProps) {
  const { t } = useTranslation();
  const needsDecision = approval !== null && approval.status === 'pending';

  return (
    <div
      data-testid="tool-call-card"
      className="flex flex-col gap-2 rounded-nx-md border border-nx-border bg-nx-surface-raised p-3"
    >
      <details>
        <summary className="flex cursor-pointer items-center gap-2 text-sm">
          <span
            className={cn(
              'rounded-nx-full px-2 py-0.5 text-xs',
              toolCall.status === 'failed'
                ? 'bg-nx-danger text-nx-primary-fg'
                : toolCall.status === 'completed'
                  ? 'bg-nx-accent/15 text-nx-accent'
                  : 'bg-nx-surface text-nx-fg-muted',
            )}
            data-testid="tool-call-status"
          >
            {t(STATUS_LABEL[toolCall.status])}
          </span>
          <code dir="ltr" className="font-mono text-xs text-nx-fg">
            {toolCall.tool}
          </code>
          {toolCall.durationMs !== null && (
            <span className="text-xs text-nx-fg-muted">
              {t('chat.tools.duration', { ms: toolCall.durationMs })}
            </span>
          )}
        </summary>
        {toolCall.result !== null && (
          <pre
            dir="ltr"
            className="mt-2 overflow-x-auto rounded-nx-sm bg-nx-surface p-2 font-mono text-xs text-nx-fg-muted"
          >
            {JSON.stringify(toolCall.result, null, 2)}
          </pre>
        )}
      </details>

      {needsDecision && (
        <div
          role="group"
          aria-label={t('chat.approvals.groupLabel')}
          className="flex flex-col gap-2 rounded-nx-md border border-nx-border p-2"
          data-testid="tool-approval-card"
        >
          <p className="text-xs text-nx-fg">
            {t('chat.approvals.requested', { tool: toolCall.tool })}
          </p>
          {approval.reason && <p className="text-xs text-nx-fg-muted">{approval.reason}</p>}
          <div className="flex gap-2">
            <Button
              size="sm"
              data-testid="approve-tool-button"
              disabled={deciding}
              onClick={() => onDecide?.(approval, true)}
            >
              {t('chat.approvals.approve')}
            </Button>
            <Button
              size="sm"
              variant="outline"
              data-testid="reject-tool-button"
              disabled={deciding}
              onClick={() => onDecide?.(approval, false)}
            >
              {t('chat.approvals.reject')}
            </Button>
          </div>
        </div>
      )}

      {!needsDecision && approval !== null && (
        <p
          className="text-xs text-nx-fg-muted"
          data-testid="tool-approval-decision"
        >
          {approval.status === 'approved'
            ? t('chat.approvals.approved')
            : t('chat.approvals.rejected')}
        </p>
      )}

      {(toolCall.status === 'completed' || toolCall.status === 'failed') && (
        <div data-testid="tool-result">
          <p className="text-xs text-nx-fg-muted">
            {toolCall.status === 'completed'
              ? t('chat.tools.resultReady', { tool: toolCall.tool })
              : t('chat.tools.resultFailed', { tool: toolCall.tool })}
          </p>
        </div>
      )}
    </div>
  );
}
