/**
 * Agent models — mirrors docs/API.md §4.1 (and the backend schemas in
 * apps/backend/app/schemas/agents.py). Keep field names identical to the
 * contract; never invent fields here.
 */

export type AgentRuntime = 'native' | 'software_team';
export type AutonomyLevel = '0' | '1' | '2' | '3';

export interface AgentLimits {
  max_steps: number;
  timeout_seconds: number;
  max_tool_calls: number;
}

export interface AgentCreate {
  name: string;
  slug?: string;
  description?: string;
  role?: string;
  goal?: string;
  instructions?: string;
  runtime: AgentRuntime;
  connection_id?: string | null;
  model_config_json?: Record<string, unknown>;
  tools?: string[];
  limits?: AgentLimits;
  autonomy_level?: AutonomyLevel | null;
  avatar_color?: string;
}

/** Every field optional plus `change_note`; saving appends a new version. */
export interface AgentUpdate {
  name?: string;
  description?: string;
  role?: string;
  goal?: string;
  instructions?: string;
  runtime?: AgentRuntime;
  connection_id?: string | null;
  model_config_json?: Record<string, unknown>;
  tools?: string[];
  limits?: AgentLimits;
  autonomy_level?: AutonomyLevel | null;
  avatar_color?: string;
  change_note?: string;
}

export interface AgentOut {
  id: string;
  slug: string;
  name: string;
  description: string;
  role: string;
  avatar_color: string;
  is_enabled: boolean;
  is_archived: boolean;
  current_version: number;
  runtime: string;
  connection_id: string | null;
  autonomy_level: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentVersionOut {
  id: string;
  agent_id: string;
  version: number;
  name: string;
  description: string;
  role: string;
  goal: string;
  instructions: string;
  runtime: string;
  connection_id: string | null;
  model_config_json: Record<string, unknown>;
  tools: string[];
  limits: Record<string, number>;
  permissions: Record<string, unknown>;
  change_note: string;
  created_at: string;
}

export interface AgentDetail extends AgentOut {
  current_version_detail: AgentVersionOut | null;
}
