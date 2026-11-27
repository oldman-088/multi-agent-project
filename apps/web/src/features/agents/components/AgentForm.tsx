import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '../../../components/ui/button';
import { ApiError } from '../../../lib/api';
import { ErrorState } from '../../../components/ui/status';
import type { AgentCreate, AgentDetail, AgentOut, AgentRuntime, AgentUpdate } from '../types';
import { useCreateAgent, useUpdateAgent } from '../hooks';

interface AgentFormProps {
  /** null = create mode; otherwise the agent being edited. */
  agent: AgentOut | null;
  /** Full detail (with current_version_detail) used to prefill an edit. */
  detail: AgentDetail | null;
  onSaved: () => void;
  onCancel: () => void;
}

interface FormState {
  name: string;
  description: string;
  role: string;
  goal: string;
  instructions: string;
  runtime: AgentRuntime;
  tools: string;
  changeNote: string;
}

function initialState(agent: AgentOut | null, detail: AgentDetail | null): FormState {
  const version = detail?.current_version_detail ?? null;
  return {
    name: agent?.name ?? '',
    description: agent?.description ?? '',
    role: agent?.role ?? '',
    goal: version?.goal ?? '',
    instructions: version?.instructions ?? '',
    runtime: agent?.runtime === 'software_team' ? 'software_team' : 'native',
    tools: (version?.tools ?? []).join(', '),
    changeNote: '',
  };
}

/**
 * Create/edit agent form (SPEC §9 "Agents (list, form, version history)").
 * Saving an edit appends a new immutable version (docs/API.md §4).
 */
export function AgentForm({ agent, detail, onSaved, onCancel }: AgentFormProps) {
  const { t } = useTranslation();
  const createAgent = useCreateAgent();
  const updateAgent = useUpdateAgent();
  const [form, setForm] = useState<FormState>(() => initialState(agent, detail));
  const [nameError, setNameError] = useState<string | null>(null);

  const versionId = detail?.current_version_detail?.id ?? null;
  useEffect(() => {
    setForm(initialState(agent, detail));
    setNameError(null);
    createAgent.reset();
    updateAgent.reset();
    // Reset when switching between create/edit targets or when the version
    // detail finishes loading.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent?.id ?? null, versionId]);

  const editing = agent !== null;
  const pending = createAgent.isPending || updateAgent.isPending;

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const name = form.name.trim();
    if (!name) {
      setNameError(t('agents.form.nameRequired'));
      return;
    }
    setNameError(null);

    const tools = form.tools
      .split(',')
      .map((tool) => tool.trim())
      .filter((tool) => tool.length > 0);

    try {
      if (editing && agent) {
        const body: AgentUpdate = {
          name,
          description: form.description.trim(),
          role: form.role.trim(),
          goal: form.goal.trim(),
          instructions: form.instructions.trim(),
          runtime: form.runtime,
          tools,
          change_note: form.changeNote.trim(),
        };
        await updateAgent.mutateAsync({ id: agent.id, body });
      } else {
        const body: AgentCreate = {
          name,
          description: form.description.trim(),
          role: form.role.trim(),
          goal: form.goal.trim(),
          instructions: form.instructions.trim(),
          runtime: form.runtime,
          tools,
        };
        await createAgent.mutateAsync(body);
      }
      onSaved();
    } catch {
      // Error state is rendered from the mutation result below.
    }
  }

  const failure = createAgent.error ?? updateAgent.error;
  const errorMessage =
    failure instanceof ApiError
      ? failure.message
      : failure
        ? t('states.errorTitle')
        : null;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
      {errorMessage && <ErrorState message={errorMessage} />}

      <div className="flex flex-col gap-1">
        <label htmlFor="agent-name-input" className="text-sm font-medium text-nx-fg">
          {t('agents.form.name')}
        </label>
        <input
          id="agent-name-input"
          data-testid="agent-name-input"
          type="text"
          required
          value={form.name}
          aria-invalid={nameError !== null}
          aria-describedby={nameError ? 'agent-name-error' : undefined}
          onChange={(event) => set('name', event.target.value)}
          className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
        />
        {nameError && (
          <p id="agent-name-error" className="text-xs text-nx-danger">
            {nameError}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="agent-description-input" className="text-sm font-medium text-nx-fg">
          {t('agents.form.description')}
        </label>
        <input
          id="agent-description-input"
          data-testid="agent-description-input"
          type="text"
          value={form.description}
          onChange={(event) => set('description', event.target.value)}
          className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="agent-role-input" className="text-sm font-medium text-nx-fg">
          {t('agents.form.role')}
        </label>
        <input
          id="agent-role-input"
          data-testid="agent-role-input"
          type="text"
          value={form.role}
          onChange={(event) => set('role', event.target.value)}
          className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="agent-goal-input" className="text-sm font-medium text-nx-fg">
          {t('agents.form.goal')}
        </label>
        <textarea
          id="agent-goal-input"
          data-testid="agent-goal-input"
          rows={2}
          value={form.goal}
          onChange={(event) => set('goal', event.target.value)}
          className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="agent-instructions-input" className="text-sm font-medium text-nx-fg">
          {t('agents.form.instructions')}
        </label>
        <textarea
          id="agent-instructions-input"
          data-testid="agent-instructions-input"
          rows={3}
          value={form.instructions}
          onChange={(event) => set('instructions', event.target.value)}
          className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="agent-runtime-select" className="text-sm font-medium text-nx-fg">
          {t('agents.form.runtime')}
        </label>
        <select
          id="agent-runtime-select"
          data-testid="agent-runtime-select"
          value={form.runtime}
          onChange={(event) => set('runtime', event.target.value as AgentRuntime)}
          className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
        >
          <option value="native">{t('agents.form.runtimeNative')}</option>
          <option value="software_team">{t('agents.form.runtimeSoftwareTeam')}</option>
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="agent-tools-input" className="text-sm font-medium text-nx-fg">
          {t('agents.form.tools')}
        </label>
        <input
          id="agent-tools-input"
          data-testid="agent-tools-input"
          type="text"
          dir="ltr"
          value={form.tools}
          onChange={(event) => set('tools', event.target.value)}
          placeholder={t('agents.form.toolsPlaceholder')}
          className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 font-mono text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
        />
        <p className="text-xs text-nx-fg-muted">{t('agents.form.toolsHint')}</p>
      </div>

      {editing && (
        <div className="flex flex-col gap-1">
          <label htmlFor="agent-change-note-input" className="text-sm font-medium text-nx-fg">
            {t('agents.form.changeNote')}
          </label>
          <input
            id="agent-change-note-input"
            data-testid="agent-change-note-input"
            type="text"
            value={form.changeNote}
            onChange={(event) => set('changeNote', event.target.value)}
            className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
          />
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          {t('agents.form.cancel')}
        </Button>
        <Button type="submit" data-testid="save-agent-button" disabled={pending}>
          {editing ? t('agents.form.saveEdit') : t('agents.form.saveCreate')}
        </Button>
      </div>
    </form>
  );
}
