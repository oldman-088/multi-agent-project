import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '../../../components/ui/button';
import { ErrorState } from '../../../components/ui/status';
import { ApiError } from '../../../lib/api';
import { useCreateConnection, usePairDevice } from '../hooks';
import type { PairingResponse, ProviderOut } from '../types';

interface PairDeviceDialogProps {
  providers: ProviderOut[];
  onSaved: () => void;
  onCancel: () => void;
}

/**
 * Bridge pairing flow (docs/API.md §7.2): generate a one-time pairing
 * credential, confirm it, then save the browser-session connection. The
 * credential is displayed exactly once — only its hash is stored server-side
 * (§7.3) — and the save step is gated on the operator having it in hand.
 */
export function PairDeviceDialog({ providers, onSaved, onCancel }: PairDeviceDialogProps) {
  const { t } = useTranslation();
  const pairDevice = usePairDevice();
  const createConnection = useCreateConnection();
  const [label, setLabel] = useState('');
  const [userscriptVersion, setUserscriptVersion] = useState('1.0.0');
  const [pairing, setPairing] = useState<PairingResponse | null>(null);
  const [confirmedCode, setConfirmedCode] = useState('');
  const [providerSlug, setProviderSlug] = useState('');
  const [labelError, setLabelError] = useState<string | null>(null);

  const activeProvider =
    providerSlug || providers.find((provider) => provider.enabled)?.slug || 'mock';
  const codeMatches = pairing !== null && confirmedCode.trim() === pairing.credential;
  const pending = pairDevice.isPending || createConnection.isPending;

  async function handlePair(event: FormEvent) {
    event.preventDefault();
    const trimmed = label.trim();
    if (!trimmed) {
      setLabelError(t('connections.pair.labelRequired'));
      return;
    }
    setLabelError(null);
    try {
      const response = await pairDevice.mutateAsync({
        label: trimmed,
        userscript_version: userscriptVersion.trim() || '1.0.0',
      });
      setPairing(response);
    } catch {
      // Error banner renders from the mutation result.
    }
  }

  async function handleSave() {
    if (!pairing || !codeMatches) {
      return;
    }
    try {
      await createConnection.mutateAsync({
        name: label.trim(),
        provider_slug: activeProvider,
        kind: 'browser_session',
      });
      onSaved();
    } catch {
      // Error banner renders from the mutation result.
    }
  }

  const failure = pairDevice.error ?? createConnection.error;
  const errorMessage =
    failure instanceof ApiError ? failure.message : failure ? t('states.errorTitle') : null;

  return (
    <div className="flex flex-col gap-4">
      {errorMessage && <ErrorState message={errorMessage} />}

      {pairing === null ? (
        <form onSubmit={handlePair} className="flex flex-col gap-4" noValidate>
          <div className="flex flex-col gap-1">
            <label htmlFor="device-label-input" className="text-sm font-medium text-nx-fg">
              {t('connections.pair.label')}
            </label>
            <input
              id="device-label-input"
              data-testid="device-label-input"
              type="text"
              required
              value={label}
              aria-invalid={labelError !== null}
              onChange={(event) => setLabel(event.target.value)}
              className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
            />
            {labelError && <p className="text-xs text-nx-danger">{labelError}</p>}
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor="userscript-version-input" className="text-sm font-medium text-nx-fg">
              {t('connections.pair.userscriptVersion')}
            </label>
            <input
              id="userscript-version-input"
              data-testid="userscript-version-input"
              type="text"
              dir="ltr"
              value={userscriptVersion}
              onChange={(event) => setUserscriptVersion(event.target.value)}
              className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 font-mono text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
            />
          </div>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onCancel}>
              {t('connections.pair.cancel')}
            </Button>
            <Button type="submit" data-testid="pair-device-button" disabled={pending}>
              {t('connections.pair.generate')}
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium text-nx-fg">
              {t('connections.pair.codeTitle')}
            </span>
            <p className="text-xs text-nx-fg-muted">
              {t('connections.pair.codeOnce', { seconds: pairing.expires_in })}
            </p>
            <code
              dir="ltr"
              data-testid="pairing-code-display"
              className="rounded-nx-md border border-nx-border bg-nx-surface-raised px-3 py-2 font-mono text-sm text-nx-fg"
            >
              {pairing.credential}
            </code>
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor="pairing-code-input" className="text-sm font-medium text-nx-fg">
              {t('connections.pair.confirmCode')}
            </label>
            <input
              id="pairing-code-input"
              data-testid="pairing-code-input"
              type="text"
              dir="ltr"
              value={confirmedCode}
              onChange={(event) => setConfirmedCode(event.target.value)}
              className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 font-mono text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
            />
            <p className="text-xs text-nx-fg-muted">{t('connections.pair.confirmHint')}</p>
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor="connection-provider-select" className="text-sm font-medium text-nx-fg">
              {t('connections.pair.provider')}
            </label>
            <select
              id="connection-provider-select"
              data-testid="connection-provider-select"
              value={activeProvider}
              onChange={(event) => setProviderSlug(event.target.value)}
              className="rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
            >
              {providers.map((provider) => (
                <option key={provider.id} value={provider.slug}>
                  {provider.display_name}
                </option>
              ))}
              {providers.length === 0 && <option value="mock">mock</option>}
            </select>
          </div>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onCancel}>
              {t('connections.pair.cancel')}
            </Button>
            <Button
              type="button"
              data-testid="save-connection-button"
              disabled={!codeMatches || pending}
              onClick={() => void handleSave()}
            >
              {t('connections.pair.save')}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
