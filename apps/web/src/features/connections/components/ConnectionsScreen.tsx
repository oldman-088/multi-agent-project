import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link2 } from 'lucide-react';
import { Button } from '../../../components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '../../../components/ui/dialog';
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/status';
import { ApiError } from '../../../lib/api';
import { DeviceList } from './DeviceList';
import { PairDeviceDialog } from './PairDeviceDialog';
import {
  useBrowserSessions,
  useConnections,
  useDevices,
  useProviders,
  useRevokeDevice,
} from '../hooks';
import type { DeviceOut } from '../types';

/** Connections screen (SPEC §8.3-I): bridge devices, pairing and connections. */
export function ConnectionsScreen() {
  const { t } = useTranslation();
  const devicesQuery = useDevices();
  const connectionsQuery = useConnections();
  const sessionsQuery = useBrowserSessions();
  const providersQuery = useProviders();
  const revokeDevice = useRevokeDevice();
  const [pairOpen, setPairOpen] = useState(false);

  const errorMessage = (error: unknown) =>
    error instanceof ApiError ? error.message : t('states.errorTitle');

  function handleRevoke(device: DeviceOut) {
    revokeDevice.mutate(device.id);
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold text-nx-fg" data-testid="connections-heading">
          {t('connections.heading')}
        </h1>
        <Button data-testid="start-pairing-button" onClick={() => setPairOpen(true)}>
          <Link2 className="h-4 w-4" aria-hidden="true" />
          {t('connections.pairDevice')}
        </Button>
      </div>

      <section className="flex flex-col gap-2" aria-labelledby="devices-heading">
        <h2 id="devices-heading" className="text-base font-medium text-nx-fg">
          {t('connections.devices.heading')}
        </h2>

        {devicesQuery.isPending && <LoadingState />}

        {devicesQuery.isError && (
          <ErrorState
            message={errorMessage(devicesQuery.error)}
            onRetry={() => void devicesQuery.refetch()}
          />
        )}

        {devicesQuery.isSuccess && devicesQuery.data.length === 0 && (
          <EmptyState
            title={t('connections.devices.emptyTitle')}
            description={t('connections.devices.emptyDescription')}
            action={{
              label: t('connections.pairDevice'),
              onClick: () => setPairOpen(true),
              testId: 'empty-start-pairing-button',
            }}
          />
        )}

        {devicesQuery.isSuccess && devicesQuery.data.length > 0 && (
          <DeviceList devices={devicesQuery.data} onRevoke={handleRevoke} />
        )}
      </section>

      <section className="flex flex-col gap-2" aria-labelledby="connections-list-heading">
        <h2 id="connections-list-heading" className="text-base font-medium text-nx-fg">
          {t('connections.connections.heading')}
        </h2>

        {connectionsQuery.isPending && <LoadingState />}

        {connectionsQuery.isError && (
          <ErrorState
            message={errorMessage(connectionsQuery.error)}
            onRetry={() => void connectionsQuery.refetch()}
          />
        )}

        {connectionsQuery.isSuccess && connectionsQuery.data.length === 0 && (
          <p className="text-sm text-nx-fg-muted">{t('connections.connections.empty')}</p>
        )}

        {connectionsQuery.isSuccess && connectionsQuery.data.length > 0 && (
          <ul className="flex flex-col gap-2" data-testid="connections-list">
            {connectionsQuery.data.map((connection) => (
              <li
                key={connection.id}
                data-testid="connection-row"
                className="flex flex-wrap items-center gap-3 rounded-nx-lg border border-nx-border bg-nx-surface p-4"
              >
                <div className="flex min-w-32 flex-1 flex-col gap-0.5">
                  <span className="text-sm font-medium text-nx-fg">{connection.name}</span>
                  <span dir="ltr" className="text-start font-mono text-xs text-nx-fg-muted">
                    {connection.provider_slug} · {connection.kind}
                  </span>
                </div>
                <span className="rounded-nx-full bg-nx-surface-raised px-2 py-0.5 text-xs text-nx-fg-muted">
                  {t(`connections.status.${connection.status}`)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2" aria-labelledby="sessions-heading">
        <h2 id="sessions-heading" className="text-base font-medium text-nx-fg">
          {t('connections.sessions.heading')}
        </h2>

        {sessionsQuery.isError && (
          <ErrorState
            message={errorMessage(sessionsQuery.error)}
            onRetry={() => void sessionsQuery.refetch()}
          />
        )}

        {sessionsQuery.isSuccess && sessionsQuery.data.length === 0 && (
          <p className="text-sm text-nx-fg-muted">{t('connections.sessions.empty')}</p>
        )}

        {sessionsQuery.isSuccess && sessionsQuery.data.length > 0 && (
          <ul className="flex flex-col gap-2" data-testid="sessions-list">
            {sessionsQuery.data.map((session) => (
              <li
                key={session.id}
                data-testid="session-row"
                className="flex flex-wrap items-center gap-3 rounded-nx-lg border border-nx-border bg-nx-surface p-4"
              >
                <div className="flex min-w-32 flex-1 flex-col gap-0.5">
                  <span dir="ltr" className="text-start font-mono text-xs text-nx-fg">
                    {session.provider_slug}
                  </span>
                  <span dir="ltr" className="text-start text-xs text-nx-fg-muted">
                    {session.url ?? '—'}
                  </span>
                </div>
                <span
                  data-testid="session-state"
                  className="rounded-nx-full bg-nx-accent/15 px-2 py-0.5 text-xs text-nx-accent"
                >
                  {session.state}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Dialog
        open={pairOpen}
        onOpenChange={(open) => {
          setPairOpen(open);
        }}
      >
        <DialogContent data-testid="pair-device-dialog">
          <DialogTitle>{t('connections.pair.title')}</DialogTitle>
          <DialogDescription>{t('connections.pair.description')}</DialogDescription>
          <PairDeviceDialog
            providers={providersQuery.data ?? []}
            onSaved={() => setPairOpen(false)}
            onCancel={() => setPairOpen(false)}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
