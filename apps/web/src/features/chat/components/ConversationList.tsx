import { useTranslation } from 'react-i18next';
import { Plus } from 'lucide-react';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../lib/utils';
import type { ConversationOut } from '../types';
import type { AgentOut } from '../../agents/types';

interface ConversationListProps {
  conversations: ConversationOut[];
  agents: AgentOut[];
  selectedId: string | null;
  selectedAgentId: string;
  creating: boolean;
  onSelect: (conversation: ConversationOut) => void;
  onSelectAgent: (agentId: string) => void;
  onNewChat: () => void;
}

/** Recent conversations + agent picker for new chats (SPEC §8.3-D). */
export function ConversationList({
  conversations,
  agents,
  selectedId,
  selectedAgentId,
  creating,
  onSelect,
  onSelectAgent,
  onNewChat,
}: ConversationListProps) {
  const { t } = useTranslation();

  return (
    <aside className="flex w-full shrink-0 flex-col gap-3 border-e border-nx-border p-3 md:w-56">
      <Button
        size="sm"
        data-testid="new-chat-button"
        onClick={onNewChat}
        disabled={creating || agents.length === 0}
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
        {t('chat.newChat')}
      </Button>

      <div className="flex flex-col gap-1">
        <label htmlFor="chat-agent-select" className="text-xs text-nx-fg-muted">
          {t('chat.agentLabel')}
        </label>
        <select
          id="chat-agent-select"
          data-testid="chat-agent-select"
          value={selectedAgentId}
          onChange={(event) => onSelectAgent(event.target.value)}
          className="rounded-nx-md border border-nx-border bg-nx-surface px-2 py-1.5 text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
        >
          {agents.length === 0 && <option value="">{t('chat.noAgents')}</option>}
          {agents.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
      </div>

      <nav aria-label={t('chat.conversationsNav')} className="flex flex-col gap-1">
        <ul className="flex flex-col gap-1" data-testid="conversations-list">
          {conversations.map((conversation) => (
            <li key={conversation.id}>
              <button
                type="button"
                data-testid="conversation-row"
                onClick={() => onSelect(conversation)}
                className={cn(
                  'w-full rounded-nx-md px-2 py-1.5 text-start text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus',
                  conversation.id === selectedId
                    ? 'bg-nx-accent/15 font-medium text-nx-accent'
                    : 'text-nx-fg-muted hover:bg-nx-surface-raised hover:text-nx-fg',
                )}
              >
                {conversation.title || t('chat.untitled')}
              </button>
            </li>
          ))}
        </ul>
        {conversations.length === 0 && (
          <p className="text-xs text-nx-fg-muted">{t('chat.noConversations')}</p>
        )}
      </nav>
    </aside>
  );
}
