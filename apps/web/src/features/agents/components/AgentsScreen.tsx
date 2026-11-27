import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus } from 'lucide-react';
import { Button } from '../../../components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '../../../components/ui/dialog';
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/status';
import { ApiError } from '../../../lib/api';
import { AgentForm } from './AgentForm';
import { AgentList } from './AgentList';
import { useAgent, useAgents, useArchiveAgent, useSetAgentEnabled } from '../hooks';
import type { AgentOut } from '../types';

/** Agents screen: list + create/edit form (SPEC §8.4 feature layout). */
export function AgentsScreen() {
  const { t } = useTranslation();
  const agentsQuery = useAgents();
  const setEnabled = useSetAgentEnabled();
  const archiveAgent = useArchiveAgent();
  const [editing, setEditing] = useState<AgentOut | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const detailQuery = useAgent(editing?.id ?? null);

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }

  function openEdit(agent: AgentOut) {
    setEditing(agent);
    setFormOpen(true);
  }

  const errorMessage = (error: unknown) =>
    error instanceof ApiError ? error.message : t('states.errorTitle');

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold text-nx-fg" data-testid="agents-heading">
          {t('agents.heading')}
        </h1>
        <Button data-testid="create-agent-button" onClick={openCreate}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          {t('agents.create')}
        </Button>
      </div>

      {agentsQuery.isPending && <LoadingState />}

      {agentsQuery.isError && (
        <ErrorState message={errorMessage(agentsQuery.error)} onRetry={() => void agentsQuery.refetch()} />
      )}

      {agentsQuery.isSuccess && agentsQuery.data.items.length === 0 && (
        <EmptyState
          title={t('agents.emptyTitle')}
          description={t('agents.emptyDescription')}
          action={{ label: t('agents.create'), onClick: openCreate, testId: 'empty-create-agent-button' }}
        />
      )}

      {agentsQuery.isSuccess && agentsQuery.data.items.length > 0 && (
        <AgentList
          agents={agentsQuery.data.items}
          onEdit={openEdit}
          onToggleEnabled={(agent) =>
            setEnabled.mutate({ id: agent.id, enabled: !agent.is_enabled })
          }
          onArchive={(agent) => archiveAgent.mutate(agent.id)}
        />
      )}

      <Dialog
        open={formOpen}
        onOpenChange={(open) => {
          setFormOpen(open);
          if (!open) {
            setEditing(null);
          }
        }}
      >
        <DialogContent data-testid="agent-form-dialog">
          <DialogTitle>
            {editing ? t('agents.editTitle') : t('agents.createTitle')}
          </DialogTitle>
          <DialogDescription>
            {editing ? t('agents.editDescription') : t('agents.createDescription')}
          </DialogDescription>
          <AgentForm
            agent={editing}
            detail={detailQuery.data ?? null}
            onSaved={() => {
              setFormOpen(false);
              setEditing(null);
            }}
            onCancel={() => {
              setFormOpen(false);
              setEditing(null);
            }}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
