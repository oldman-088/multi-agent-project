/**
 * Chat/run models — mirrors docs/API.md §4.1 (conversations, messages),
 * §5.1 (runs, events, approvals) and the backend schemas in
 * apps/backend/app/schemas/{agents,runs}.py. Field names follow the contract.
 */

export interface ConversationOut {
  id: string;
  agent_id: string;
  title: string;
  is_archived: boolean;
  last_message_at: string | null;
  created_at: string;
}

export type MessageRole = 'user' | 'assistant' | 'tool' | 'system';

export interface MessageOut {
  id: string;
  conversation_id: string;
  run_id: string | null;
  role: string;
  content: string;
  tool_calls: unknown[];
  attachments: unknown[];
  usage: Record<string, unknown> | null;
  sequence: number;
  created_at: string;
}

export type RunStatus =
  | 'created'
  | 'running'
  | 'paused'
  | 'waiting_for_user'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'resume_available';

export type RunTrigger = 'manual' | 'chat' | 'schedule' | 'file_watch' | 'git_event';

export interface RunOut {
  id: string;
  agent_id: string;
  agent_version_id: string | null;
  conversation_id: string | null;
  connection_id: string | null;
  status: RunStatus;
  trigger: RunTrigger;
  directive: string;
  last_sequence: number;
  step_count: number;
  tool_call_count: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

/** SPEC §7 event envelope (docs/API.md §5.1). */
export interface EventOut {
  event_id: string;
  event_version: number;
  organization_id: string;
  run_id: string | null;
  task_id: string | null;
  agent_id: string | null;
  correlation_id: string | null;
  sequence: number;
  event_type: string;
  timestamp: string;
  source_runtime: string;
  payload: Record<string, unknown>;
}

export type ApprovalKind = 'tool_call' | 'plan' | 'merge';
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired';

export interface ApprovalOut {
  id: string;
  kind: ApprovalKind;
  status: ApprovalStatus;
  run_id: string | null;
  agent_id: string | null;
  tool_slug: string | null;
  requested_payload: Record<string, unknown>;
  reason: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}
