/**
 * Run event stream → chat view state (SPEC §8.3-D "live streaming").
 *
 * `applyEvents` is a pure reducer over the documented event envelope of
 * docs/API.md §5.1 (`EventOut`). Streaming deltas arrive as `agent.stream`
 * events; the reducer is keyed per run and per message id — never a shared
 * "current message" (SPEC §8.4 stream isolation).
 *
 * Payload field names are the one documented assumption of this boundary:
 * `agent.stream` carries `delta` (preferred) or `text`/`content`, optionally
 * `message_id`; `agent.message` carries `content` and optionally `message_id`.
 */
import type { ApprovalStatus, EventOut } from './types';

export type ToolCallStatus = 'running' | 'awaiting_approval' | 'completed' | 'failed';

export interface ToolCallView {
  id: string;
  tool: string;
  status: ToolCallStatus;
  outcome: string | null;
  durationMs: number | null;
  result: Record<string, unknown> | null;
  startedAt: string | null;
}

export interface ApprovalView {
  id: string;
  tool: string | null;
  reason: string;
  status: ApprovalStatus;
}

export interface StreamMessageView {
  id: string;
  content: string;
  streaming: boolean;
  createdAt: string | null;
}

export interface RunStreamState {
  runId: string;
  /** Run status derived from run.* events ('idle' before any arrives). */
  runStatus: 'idle' | 'running' | 'paused' | 'waiting_for_user' | 'completed' | 'failed' | 'cancelled';
  messages: StreamMessageView[];
  toolCalls: ToolCallView[];
  approvals: ApprovalView[];
  /** Highest applied sequence — the resume cursor. */
  lastSequence: number;
  done: boolean;
}

export function initialStreamState(runId: string): RunStreamState {
  return {
    runId,
    runStatus: 'idle',
    messages: [],
    toolCalls: [],
    approvals: [],
    lastSequence: 0,
    done: false,
  };
}

function readString(payload: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === 'string') {
      return value;
    }
  }
  return null;
}

/** Documented boundary: stream delta extraction from agent.stream payloads. */
export function readStreamDelta(payload: Record<string, unknown>): string {
  return readString(payload, 'delta', 'text', 'content') ?? '';
}

function messageIdOf(payload: Record<string, unknown>, runId: string, sequence: number): string {
  return readString(payload, 'message_id', 'messageId') ?? `live:${runId}:${sequence}`;
}

function upsertToolCall(
  calls: ToolCallView[],
  match: (call: ToolCallView) => boolean,
  fallback: () => ToolCallView,
  patch: Partial<ToolCallView>,
): ToolCallView[] {
  const index = calls.findIndex(match);
  if (index === -1) {
    return [...calls, { ...fallback(), ...patch }];
  }
  const next = [...calls];
  next[index] = { ...next[index], ...patch };
  return next;
}

function toolOf(payload: Record<string, unknown>): string {
  return readString(payload, 'tool', 'tool_slug', 'slug') ?? 'tool';
}

/**
 * Applies new events to the stream state. Pure and order-sensitive: events
 * are applied in ascending `sequence`; duplicates and stale events (sequence
 * already applied) are ignored, so the cursor can be replayed safely.
 */
export function applyEvents(state: RunStreamState, events: EventOut[]): RunStreamState {
  let next: RunStreamState = state;
  const ordered = [...events].sort((a, b) => a.sequence - b.sequence);

  for (const event of ordered) {
    if (event.run_id !== null && event.run_id !== state.runId) {
      continue;
    }
    if (event.sequence <= next.lastSequence && next.lastSequence !== 0) {
      continue;
    }

    const payload = event.payload ?? {};
    const at = event.timestamp;

    switch (true) {
      case event.event_type === 'agent.stream': {
        const messageId = messageIdOf(payload, state.runId, event.sequence);
        const delta = readStreamDelta(payload);
        next = {
          ...next,
          messages: appendDelta(next.messages, messageId, delta, at),
        };
        break;
      }
      case event.event_type === 'agent.message': {
        const messageId = messageIdOf(payload, state.runId, event.sequence);
        const content = readString(payload, 'content', 'text', 'delta') ?? '';
        next = {
          ...next,
          messages: finalizeMessage(next.messages, messageId, content, at),
        };
        break;
      }
      case event.event_type === 'tool.execution.started': {
        const tool = toolOf(payload);
        const awaiting = readString(payload, 'outcome') === 'awaiting_approval';
        next = {
          ...next,
          toolCalls: upsertToolCall(
            next.toolCalls,
            (call) => call.tool === tool && call.status === 'running',
            () => ({
              id: `tool:${state.runId}:${event.sequence}`,
              tool,
              status: 'running',
              outcome: null,
              durationMs: null,
              result: null,
              startedAt: at,
            }),
            { status: awaiting ? 'awaiting_approval' : 'running', outcome: readString(payload, 'outcome') },
          ),
        };
        break;
      }
      case event.event_type === 'tool.execution.completed':
      case event.event_type === 'tool.execution.failed': {
        const tool = toolOf(payload);
        const failed = event.event_type === 'tool.execution.failed';
        const durationMs = typeof payload.duration_ms === 'number' ? payload.duration_ms : null;
        const result =
          typeof payload.result === 'object' && payload.result !== null
            ? (payload.result as Record<string, unknown>)
            : null;
        next = {
          ...next,
          toolCalls: upsertToolCall(
            next.toolCalls,
            (call) => call.tool === tool && call.status !== 'completed' && call.status !== 'failed',
            () => ({
              id: `tool:${state.runId}:${event.sequence}`,
              tool,
              status: 'running',
              outcome: null,
              durationMs: null,
              result: null,
              startedAt: at,
            }),
            {
              status: failed ? 'failed' : 'completed',
              outcome: readString(payload, 'outcome'),
              durationMs,
              result,
            },
          ),
        };
        break;
      }
      case event.event_type === 'approval.requested': {
        const approvalId = readString(payload, 'approval_id', 'approvalId') ?? `apr:${event.sequence}`;
        const tool = readString(payload, 'tool', 'tool_slug');
        const reason = readString(payload, 'reason') ?? '';
        const exists = next.approvals.some((approval) => approval.id === approvalId);
        next = {
          ...next,
          approvals: exists
            ? next.approvals
            : [...next.approvals, { id: approvalId, tool, reason, status: 'pending' }],
          toolCalls: tool
            ? upsertToolCall(
                next.toolCalls,
                (call) => call.tool === tool && call.status === 'running',
                () => ({
                  id: `tool:${state.runId}:${event.sequence}`,
                  tool,
                  status: 'running',
                  outcome: null,
                  durationMs: null,
                  result: null,
                  startedAt: at,
                }),
                { status: 'awaiting_approval' },
              )
            : next.toolCalls,
        };
        break;
      }
      case event.event_type === 'approval.approved':
      case event.event_type === 'approval.rejected': {
        const approvalId = readString(payload, 'approval_id', 'approvalId');
        const status: ApprovalStatus = event.event_type === 'approval.approved' ? 'approved' : 'rejected';
        next = {
          ...next,
          approvals: next.approvals.map((approval) =>
            approval.id === approvalId ? { ...approval, status } : approval,
          ),
        };
        break;
      }
      case event.event_type === 'run.started':
      case event.event_type === 'run.resumed': {
        next = { ...next, runStatus: 'running' };
        break;
      }
      case event.event_type === 'run.paused': {
        next = { ...next, runStatus: 'paused' };
        break;
      }
      case event.event_type === 'run.completed': {
        next = { ...next, runStatus: 'completed', done: true };
        break;
      }
      case event.event_type === 'run.failed': {
        next = { ...next, runStatus: 'failed', done: true };
        break;
      }
      case event.event_type === 'run.cancelled': {
        next = { ...next, runStatus: 'cancelled', done: true };
        break;
      }
      default:
        break;
    }

    next = { ...next, lastSequence: Math.max(next.lastSequence, event.sequence) };
  }

  // A finished run always leaves the active message out of streaming mode.
  if (next.done) {
    next = {
      ...next,
      messages: next.messages.map((message) =>
        message.streaming ? { ...message, streaming: false } : message,
      ),
    };
  }
  return next;
}

/** Marks an approval decided locally (optimistic; the run events confirm it). */
export function applyApprovalDecision(
  state: RunStreamState,
  approvalId: string,
  status: ApprovalStatus,
): RunStreamState {
  return {
    ...state,
    approvals: state.approvals.map((approval) =>
      approval.id === approvalId ? { ...approval, status } : approval,
    ),
  };
}

function appendDelta(
  messages: StreamMessageView[],
  messageId: string,
  delta: string,
  at: string,
): StreamMessageView[] {
  const index = messages.findIndex((message) => message.id === messageId);
  if (index === -1) {
    return [...messages, { id: messageId, content: delta, streaming: true, createdAt: at }];
  }
  const next = [...messages];
  next[index] = {
    ...next[index],
    content: next[index].content + delta,
    streaming: true,
  };
  return next;
}

function finalizeMessage(
  messages: StreamMessageView[],
  messageId: string,
  content: string,
  at: string,
): StreamMessageView[] {
  const index = messages.findIndex((message) => message.id === messageId);
  if (index === -1) {
    return [...messages, { id: messageId, content, streaming: false, createdAt: at }];
  }
  const next = [...messages];
  next[index] = { ...next[index], content, streaming: false };
  return next;
}
