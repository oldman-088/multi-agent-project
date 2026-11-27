import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ChatMessage } from './ChatMessage';
import { ToolCallCard } from './ToolCallCard';
import type { ApprovalView, RunStreamState } from '../event-stream';
import type { MessageOut } from '../types';

interface MessageListProps {
  history: MessageOut[];
  stream: RunStreamState;
  onDecide: (approval: ApprovalView, approve: boolean) => void;
  decidingApprovalId: string | null;
}

/**
 * Conversation thread: persisted history followed by the live run block
 * (stream messages + tool cards). Live messages that the history already
 * contains are hidden once the run is done, so completing a run never
 * duplicates the assistant reply.
 */
export function MessageList({ history, stream, onDecide, decidingApprovalId }: MessageListProps) {
  const { t } = useTranslation();
  const bottomRef = useRef<HTMLDivElement>(null);
  const messageCount = history.length + stream.messages.length;

  useEffect(() => {
    const el = bottomRef.current;
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'end' });
    }
  }, [messageCount, stream.toolCalls.length]);

  const visibleLive = stream.done
    ? stream.messages.filter(
        (live) =>
          !history.some(
            (saved) => saved.role !== 'user' && saved.content.trim() === live.content.trim(),
          ),
      )
    : stream.messages;

  return (
    <div className="flex flex-col gap-3" data-testid="message-list">
      {history.map((message) => (
        <ChatMessage
          key={message.id}
          role={message.role}
          content={message.content}
          testId={message.role === 'user' ? 'user-message' : 'assistant-message'}
        />
      ))}

      {stream.toolCalls.map((toolCall) => {
        const approval = stream.approvals.find(
          (candidate) =>
            candidate.tool === toolCall.tool &&
            (candidate.status === 'pending' || toolCall.status === 'awaiting_approval'),
        );
        return (
          <ToolCallCard
            key={toolCall.id}
            toolCall={toolCall}
            approval={approval ?? null}
            onDecide={onDecide}
            deciding={decidingApprovalId !== null && decidingApprovalId === approval?.id}
          />
        );
      })}

      {visibleLive.map((message) => (
        <ChatMessage
          key={message.id}
          role="assistant"
          content={message.content}
          streaming={message.streaming && !stream.done}
          testId="assistant-message"
        />
      ))}

      {history.length === 0 && stream.messages.length === 0 && (
        <p className="text-sm text-nx-fg-muted">{t('chat.emptyThread')}</p>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
