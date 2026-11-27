import { useTranslation } from 'react-i18next';
import { Button } from '../../../components/ui/button';
import type { DeviceOut } from '../types';

interface DeviceListProps {
  devices: DeviceOut[];
  onRevoke: (device: DeviceOut) => void;
}

/** Paired bridge devices (docs/API.md §7.2 GET /api/devices). */
export function DeviceList({ devices, onRevoke }: DeviceListProps) {
  const { t } = useTranslation();

  return (
    <ul className="flex flex-col gap-2" data-testid="devices-list">
      {devices.map((device) => (
        <li
          key={device.id}
          data-testid="device-row"
          className="flex flex-wrap items-center gap-3 rounded-nx-lg border border-nx-border bg-nx-surface p-4"
        >
          <div className="flex min-w-32 flex-1 flex-col gap-0.5">
            <span className="text-sm font-medium text-nx-fg">{device.label}</span>
            <span dir="ltr" className="text-start font-mono text-xs text-nx-fg-muted">
              {t('connections.devices.userscript', { version: device.userscript_version })}
            </span>
          </div>

          <span
            className={
              device.revoked
                ? 'rounded-nx-full bg-nx-surface-raised px-2 py-0.5 text-xs text-nx-fg-muted'
                : 'rounded-nx-full bg-nx-accent/15 px-2 py-0.5 text-xs text-nx-accent'
            }
          >
            {device.revoked ? t('connections.devices.revoked') : t('connections.devices.ready')}
          </span>

          {device.last_seen_at && (
            <span className="text-xs text-nx-fg-muted">
              {t('connections.devices.lastSeen', {
                time: new Date(device.last_seen_at).toLocaleString(),
              })}
            </span>
          )}

          {!device.revoked && (
            <Button
              size="sm"
              variant="outline"
              data-testid="revoke-device-button"
              onClick={() => onRevoke(device)}
            >
              {t('connections.devices.revoke')}
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
