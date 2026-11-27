import { useTranslation } from 'react-i18next';
import { Button } from '../../../components/ui/button';
import type { AgentOut } from '../types';

interface AgentListProps {
  agents: AgentOut[];
  onEdit: (agent: AgentOut) => void;
  onToggleEnabled: (agent: AgentOut) => void;
  onArchive: (agent: AgentOut) => void;
}

/** Agent rows (SPEC §9 "Agents (list, form)"). One row per agent with its
 * status, version and row actions. Logical spacing only (SPEC §8.2). */
export function AgentList({ agents, onEdit, onToggleEnabled, onArchive }: AgentListProps) {
  const { t } = useTranslation();

  return (
    <ul className="flex flex-col gap-2" data-testid="agents-list">
      {agents.map((agent) => (
        <li
          key={agent.id}
          data-testid="agent-row"
          className="flex flex-wrap items-center gap-3 rounded-nx-lg border border-nx-border bg-nx-surface p-4"
        >
          <span
            aria-hidden="true"
            className="h-8 w-8 shrink-0 rounded-nx-full"
            style={{ backgroundColor: agent.avatar_color }}
          />
          <div className="flex min-w-32 flex-1 flex-col gap-0.5">
            <span className="text-sm font-medium text-nx-fg">{agent.name}</span>
            <span className="text-xs text-nx-fg-muted">
              {agent.role || t('agents.roleUnset')} ·{' '}
              {t('agents.versionLabel', { version: agent.current_version })}
            </span>
          </div>

          <span
            className={
              agent.is_archived
                ? 'rounded-nx-full bg-nx-surface-raised px-2 py-0.5 text-xs text-nx-fg-muted'
                : agent.is_enabled
                  ? 'rounded-nx-full bg-nx-accent/15 px-2 py-0.5 text-xs text-nx-accent'
                  : 'rounded-nx-full bg-nx-surface-raised px-2 py-0.5 text-xs text-nx-fg-muted'
            }
          >
            {agent.is_archived
              ? t('agents.status.archived')
              : agent.is_enabled
                ? t('agents.status.enabled')
                : t('agents.status.disabled')}
          </span>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              data-testid="edit-agent-button"
              onClick={() => onEdit(agent)}
            >
              {t('agents.actions.edit')}
            </Button>
            {!agent.is_archived && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  data-testid="toggle-agent-button"
                  onClick={() => onToggleEnabled(agent)}
                >
                  {agent.is_enabled ? t('agents.actions.disable') : t('agents.actions.enable')}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  data-testid="archive-agent-button"
                  onClick={() => onArchive(agent)}
                >
                  {t('agents.actions.archive')}
                </Button>
              </>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
