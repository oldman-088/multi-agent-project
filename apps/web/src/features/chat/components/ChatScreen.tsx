import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { ErrorState, LoadingState } from '../../../components/ui/status';
import { ApiError } from '../../../lib/api';
import { useAgents } from '../../agents/hooks';
import { ConversationList } from './ConversationList';
import { ChatComposer } from './ChatComposer';
import { MessageList } from './MessageList';
import {
  chatKeys,
  useConversations,
  useCreateConversation,
  useDecideApproval,
  useMessages,
  useRunEventStream,
  useSendMessage,
  useStartRun,
} from '../hooks';
import type { ApprovalView } from '../event-stream';
import type { ConversationOut } from '../types';

/** Chat screen (SPEC §8.3-D MVP): conversations, live run streaming, inline
 * tool approvals. Every API call is a relative /api URL (docs/API.md). */
export function ChatScreen() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const agentsQuery = useAgents();
  const conversationsQuery = useConversations();
  const sendMessage = useSendMessage();
  const startRun = useStartRun();
  const createConversation = useCreateConversation();
  const decideApproval = useDecideApproval();

  const agents = useMemo(() => agentsQuery.data?.items ?? [], [agentsQuery.data]);
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [selected, setSelected] = useState<ConversationOut | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedAgentId && agents.length > 0) {
      setSelectedAgentId(agents[0].id);
    }
  }, [agents, selectedAgentId]);

  const messagesQuery = useMessages(selected?.id ?? null);
  const stream = useRunEventStream(activeRunId, { pollMs: 500 });

  // When the run reaches a terminal event, fold the result into history.
  useEffect(() => {
    if (stream.state.done && selected) {
      void queryClient.invalidateQueries({ queryKey: chatKeys.messages(selected.id) });
    }
  }, [stream.state.done, selected, queryClient]);

  const conversations = conversationsQuery.data?.items ?? [];
  const history = useMemo(
    () => [...(messagesQuery.data ?? [])].sort((a, b) => a.sequence - b.sequence),
    [messagesQuery.data],
  );

  async function handleSend(content: string) {
    setSendError(null);
    try {
      let conversation = selected;
      if (!conversation) {
        if (!selectedAgentId) {
          return;
        }
        conversation = await createConversation.mutateAsync({
          agent_id: selectedAgentId,
          title: content.slice(0, 60),
        });
        setSelected(conversation);
        await queryClient.invalidateQueries({ queryKey: chatKeys.conversations() });
      }
      await sendMessage.mutateAsync({ conversationId: conversation.id, content });
      const run = await startRun.mutateAsync({
        agent_id: selectedAgentId || conversation.agent_id,
        directive: content,
        conversation_id: conversation.id,
      });
      setActiveRunId(run.id);
    } catch (error) {
      setSendError(error instanceof ApiError ? error.message : t('states.errorTitle'));
    }
  }

  async function handleNewChat() {
    if (!selectedAgentId) {
      return;
    }
    setSendError(null);
    try {
      const conversation = await createConversation.mutateAsync({
        agent_id: selectedAgentId,
        title: t('chat.untitled'),
      });
      setSelected(conversation);
      setActiveRunId(null);
      await queryClient.invalidateQueries({ queryKey: chatKeys.conversations() });
    } catch (error) {
      setSendError(error instanceof ApiError ? error.message : t('states.errorTitle'));
    }
  }

  function handleDecide(approval: ApprovalView, approve: boolean) {
    decideApproval.mutate(
      { approvalId: approval.id, approve },
      {
        onSuccess: (decided) => {
          stream.markApproval(decided.id, decided.status);
        },
      },
    );
  }

  return (
    <div className="flex h-full min-h-[60vh] flex-col gap-4">
      <h1 className="text-2xl font-semibold text-nx-fg" data-testid="chat-heading">
        {t('chat.heading')}
      </h1>

      <div className="flex flex-1 flex-col gap-4 md:flex-row">
        {conversationsQuery.isPending ? (
          <LoadingState className="md:w-56" />
        ) : conversationsQuery.isError ? (
          <ErrorState
            className="md:w-56"
            message={
              conversationsQuery.error instanceof ApiError
                ? conversationsQuery.error.message
                : t('states.errorTitle')
            }
            onRetry={() => void conversationsQuery.refetch()}
          />
        ) : (
          <ConversationList
            conversations={conversations}
            agents={agents}
            selectedId={selected?.id ?? null}
            selectedAgentId={selectedAgentId}
            creating={createConversation.isPending}
            onSelect={(conversation) => {
              setSelected(conversation);
              setActiveRunId(null);
            }}
            onSelectAgent={setSelectedAgentId}
            onNewChat={() => void handleNewChat()}
          />
        )}

        <section className="flex flex-1 flex-col gap-3">
          {messagesQuery.isPending && selected !== null && <LoadingState />}

          {messagesQuery.isError && (
            <ErrorState
              message={
                messagesQuery.error instanceof ApiError
                  ? messagesQuery.error.message
                  : t('states.errorTitle')
              }
              onRetry={() => void messagesQuery.refetch()}
            />
          )}

          {sendError && <ErrorState message={sendError} />}

          {(messagesQuery.isSuccess || selected === null) && (
            <div className="flex-1 overflow-y-auto">
              <MessageList
                history={history}
                stream={stream.state}
                onDecide={handleDecide}
                decidingApprovalId={decideApproval.isPending ? decideApproval.variables.approvalId : null}
              />
            </div>
          )}

          {stream.error !== null && (
            <ErrorState message={t('chat.streamError')} onRetry={stream.retry} />
          )}

          <ChatComposer
            disabled={agents.length === 0}
            sending={sendMessage.isPending || startRun.isPending}
            onSend={(content) => void handleSend(content)}
          />
        </section>
      </div>
    </div>
  );
}
