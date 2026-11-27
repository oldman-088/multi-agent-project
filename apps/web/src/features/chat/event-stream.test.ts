import { describe, expect, it } from 'vitest';
import {
  applyApprovalDecision,
  applyEvents,
  initialStreamState,
  readStreamDelta,
} from './event-stream';
import type { EventOut } from './types';

function event(
  sequence: number,
  event_type: string,
  payload: Record<string, unknown> = {},
  runId = 'run_1',
): EventOut {
  return {
    event_id: `evt_${sequence}`,
    event_version: 1,
    organization_id: 'org_1',
    run_id: runId,
    task_id: null,
    agent_id: 'agt_1',
    correlation_id: null,
    sequence,
    event_type,
    timestamp: `2026-11-27T12:00:0${Math.min(sequence, 9)}+00:00`,
    source_runtime: 'native',
    payload,
  };
}

describe('run event stream reducer (SPEC 8.3-D live streaming)', () => {
  it('accumulates agent.stream deltas into one streaming message', () => {
    let state = initialStreamState('run_1');
    state = applyEvents(state, [
      event(1, 'run.started'),
      event(2, 'agent.stream', { message_id: 'msg_1', delta: 'Hello ' }),
      event(3, 'agent.stream', { message_id: 'msg_1', delta: 'world' }),
    ]);

    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]).toMatchObject({ id: 'msg_1', content: 'Hello world', streaming: true });
    expect(state.runStatus).toBe('running');
    expect(state.lastSequence).toBe(3);
  });

  it('finalizes a message on agent.message and keeps ids isolated per message', () => {
    let state = initialStreamState('run_1');
    state = applyEvents(state, [
      event(1, 'agent.stream', { message_id: 'msg_1', delta: 'partial' }),
      event(2, 'agent.stream', { message_id: 'msg_2', delta: 'other' }),
      event(3, 'agent.message', { message_id: 'msg_1', content: 'final text' }),
    ]);

    expect(state.messages.find((m) => m.id === 'msg_1')).toMatchObject({
      content: 'final text',
      streaming: false,
    });
    expect(state.messages.find((m) => m.id === 'msg_2')).toMatchObject({
      content: 'other',
      streaming: true,
    });
  });

  it('tracks the tool-call lifecycle including duration and result', () => {
    let state = initialStreamState('run_1');
    state = applyEvents(state, [
      event(1, 'tool.execution.started', { tool: 'calc.evaluate', outcome: 'running' }),
      event(2, 'tool.execution.completed', {
        tool: 'calc.evaluate',
        outcome: 'success',
        duration_ms: 42,
        result: { value: 4 },
      }),
    ]);

    expect(state.toolCalls).toHaveLength(1);
    expect(state.toolCalls[0]).toMatchObject({
      tool: 'calc.evaluate',
      status: 'completed',
      durationMs: 42,
      result: { value: 4 },
    });
  });

  it('marks tool cards awaiting approval and resolves the approval lifecycle', () => {
    let state = initialStreamState('run_1');
    state = applyEvents(state, [
      event(1, 'approval.requested', { approval_id: 'apr_1', tool: 'bash.exec', reason: 'level 0' }),
    ]);

    expect(state.toolCalls[0]).toMatchObject({ tool: 'bash.exec', status: 'awaiting_approval' });
    expect(state.approvals[0]).toMatchObject({ id: 'apr_1', status: 'pending' });

    const decided = applyApprovalDecision(state, 'apr_1', 'approved');
    expect(decided.approvals[0]).toMatchObject({ status: 'approved' });

    state = applyEvents(state, [event(2, 'approval.rejected', { approval_id: 'apr_2' })]);
    expect(state.approvals.some((a) => a.status === 'rejected')).toBe(false);
  });

  it('is idempotent on cursor replay: stale sequences are ignored', () => {
    const events = [
      event(1, 'agent.stream', { message_id: 'msg_1', delta: 'once ' }),
      event(2, 'agent.stream', { message_id: 'msg_1', delta: 'only' }),
    ];
    let state = applyEvents(initialStreamState('run_1'), events);
    state = applyEvents(state, events);

    expect(state.messages[0]).toMatchObject({ content: 'once only' });
    expect(state.lastSequence).toBe(2);
  });

  it('ignores events from other runs and sorts out-of-order arrivals', () => {
    let state = initialStreamState('run_1');
    state = applyEvents(state, [
      event(3, 'agent.stream', { message_id: 'msg_1', delta: 'B' }, 'run_1'),
      event(2, 'agent.stream', { message_id: 'msg_1', delta: 'A' }, 'run_1'),
      event(9, 'agent.stream', { message_id: 'msg_x', delta: 'nope' }, 'run_other'),
    ]);

    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]).toMatchObject({ content: 'AB' });
  });

  it('run terminal events end the stream and stop the streaming flag', () => {
    let state = applyEvents(initialStreamState('run_1'), [
      event(1, 'agent.stream', { message_id: 'msg_1', delta: 'draft' }),
    ]);
    expect(state.done).toBe(false);

    state = applyEvents(state, [event(2, 'run.completed')]);
    expect(state.done).toBe(true);
    expect(state.runStatus).toBe('completed');
    expect(state.messages[0]).toMatchObject({ streaming: false });
  });

  it('readStreamDelta accepts the documented payload aliases', () => {
    expect(readStreamDelta({ delta: 'a' })).toBe('a');
    expect(readStreamDelta({ text: 'b' })).toBe('b');
    expect(readStreamDelta({ content: 'c' })).toBe('c');
    expect(readStreamDelta({})).toBe('');
  });
});
