/**
 * Chat data hooks (SPEC §8.4). List data goes through query hooks; the
 * high-frequency run event stream lives in a dedicated store
 * (`useRunEventStream`) keyed by run id and never enters the query cache.
 */
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import {
  createConversation,
  createRun,
  decideApproval,
  listConversations,
  listMessages,
  listRunEvents,
  sendMessage,
} from './api';
import {
  applyApprovalDecision,
  applyEvents,
  initialStreamState,
  type ApprovalView,
  type RunStreamState,
} from './event-stream';
import type { ApprovalOut, ConversationOut, EventOut, MessageOut, RunOut } from './types';
import type { Page } from '../../lib/api';

export const chatKeys = {
  all: ['chat'] as const,
  conversations: () => ['chat', 'conversations'] as const,
  messages: (conversationId: string) => ['chat', 'messages', conversationId] as const,
};

export function useConversations(agentId?: string) {
  return useQuery<Page<ConversationOut>>({
    queryKey: [...chatKeys.conversations(), agentId ?? null],
    queryFn: ({ signal }) => listConversations({ agentId }, signal),
  });
}

export function useMessages(conversationId: string | null) {
  return useQuery<MessageOut[]>({
    queryKey: chatKeys.messages(conversationId ?? ''),
    queryFn: ({ signal }) => listMessages(conversationId as string, undefined, signal),
    enabled: conversationId !== null,
  });
}

export function useCreateConversation(): UseMutationResult<
  ConversationOut,
  Error,
  { agent_id: string; title?: string }
> {
  const queryClient = useQueryClient();
  return useMutation<ConversationOut, Error, { agent_id: string; title?: string }>({
    mutationFn: (body) => createConversation(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: chatKeys.conversations() }),
  });
}

export function useSendMessage(): UseMutationResult<
  MessageOut,
  Error,
  { conversationId: string; content: string }
> {
  const queryClient = useQueryClient();
  return useMutation<MessageOut, Error, { conversationId: string; content: string }>({
    mutationFn: ({ conversationId, content }) => sendMessage(conversationId, { content }),
    onSuccess: (message) =>
      queryClient.invalidateQueries({ queryKey: chatKeys.messages(message.conversation_id) }),
  });
}

export function useStartRun(): UseMutationResult<RunOut, Error, { agent_id: string; directive: string; conversation_id?: string | null }> {
  return useMutation<RunOut, Error, { agent_id: string; directive: string; conversation_id?: string | null }>({
    mutationFn: ({ agent_id, directive, conversation_id }) =>
      createRun({ agent_id, directive, conversation_id, trigger: 'chat' }),
  });
}

export function useDecideApproval(): UseMutationResult<
  ApprovalOut,
  Error,
  { approvalId: string; approve: boolean; note?: string }
> {
  return useMutation<ApprovalOut, Error, { approvalId: string; approve: boolean; note?: string }>({
    mutationFn: ({ approvalId, approve, note }) => decideApproval(approvalId, { approve, note }),
  });
}

export interface RunStreamOptions {
  /** Poll interval for the event cursor; smaller values mainly aid tests. */
  pollMs?: number;
}

export interface RunStreamResult {
  state: RunStreamState;
  /** Error from the last cursor fetch (stream keeps its state on error). */
  error: unknown;
  /** Local optimistic decision, confirmed by subsequent run events. */
  markApproval: (approvalId: string, status: ApprovalView['status']) => void;
  retry: () => void;
}

type StreamAction =
  | { kind: 'events'; events: EventOut[] }
  | { kind: 'approval'; approvalId: string; status: ApprovalView['status'] }
  | { kind: 'reset'; runId: string };

function streamReducer(current: RunStreamState, action: StreamAction): RunStreamState {
  switch (action.kind) {
    case 'events':
      return applyEvents(current, action.events);
    case 'approval':
      return applyApprovalDecision(current, action.approvalId, action.status);
    case 'reset':
      return initialStreamState(action.runId);
    default:
      return current;
  }
}

/**
 * Live run event stream: follows `GET /api/runs/{id}/events?after_sequence=…`
 * (the resume cursor of docs/API.md §5.2) and folds events into the chat
 * view state. Polling stops when the run reaches a terminal event.
 */
export function useRunEventStream(
  runId: string | null,
  options: RunStreamOptions = {},
): RunStreamResult {
  const { pollMs = 750 } = options;
  const [state, dispatch] = useReducer(streamReducer, runId ?? '', (id) => initialStreamState(id));
  const [error, setError] = useState<unknown>(null);
  const [retryToken, setRetryToken] = useState(0);
  const cursorRef = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;

  // Reset when the stream target changes.
  useEffect(() => {
    cursorRef.current = 0;
    setError(null);
    dispatch({ kind: 'reset', runId: runId ?? '' });
  }, [runId]);

  useEffect(() => {
    if (!runId) {
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      if (cancelled) {
        return;
      }
      try {
        const events = await listRunEvents(runId as string, cursorRef.current);
        if (cancelled) {
          return;
        }
        setError(null);
        if (events.length > 0) {
          cursorRef.current = events.reduce(
            (max, event) => Math.max(max, event.sequence),
            cursorRef.current,
          );
          dispatch({ kind: 'events', events });
        }
        if (!stateRef.current.done) {
          timer = setTimeout(() => void poll(), pollMs);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err);
          // Keep trying: the stream resumes from the same cursor.
          timer = setTimeout(() => void poll(), pollMs * 2);
        }
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    };
  }, [runId, pollMs, retryToken]);

  const markApproval = useCallback((approvalId: string, status: ApprovalView['status']) => {
    dispatch({ kind: 'approval', approvalId, status });
  }, []);

  const retry = useCallback(() => setRetryToken((token) => token + 1), []);

  return { state, error, markApproval, retry };
}
