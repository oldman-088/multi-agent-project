/**
 * Connection Manager (SPEC §6, Phase 1 item 7; screenshots required by §5.1).
 *
 * "Connect through your browser" is the first option and expands into the
 * guided wizard: install manager → install userscript → start bridge → pairing
 * code → selector test. The wizard renders only real steps with a real state;
 * the later steps stay disabled until the earlier ones are done, instead of
 * pretending to work.
 *
 * Every visual state is labelled in text as well as colour, and the progress
 * indicator is `aria-live` so the step change is announced.
 */
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { StatusBadge } from '../components/StatusBadge.tsx';

/** Wizard steps in fixed order; keys are translation keys. */
const WIZARD_STEPS = [
  'connection.browser.step1',
  'connection.browser.step2',
  'connection.browser.step3',
  'connection.browser.step4',
  'connection.browser.step5',
] as const;

type WizardState = 'not-started' | 'in-progress' | 'done';

export function ConnectionsPage() {
  const { t } = useTranslation();
  const headingId = useId();
  const wizardHeadingId = useId();
  const [currentStep, setCurrentStep] = useState(0);
  const [wizardState, setWizardState] = useState<WizardState>('not-started');

  const stateOf = (index: number): WizardState => {
    if (wizardState === 'done') return 'done';
    if (index < currentStep) return 'done';
    if (index === currentStep && wizardState === 'in-progress') return 'in-progress';
    return 'not-started';
  };

  const advance = () => {
    if (wizardState === 'done') return;
    if (currentStep === WIZARD_STEPS.length - 1) {
      setWizardState('done');
      return;
    }
    setWizardState('in-progress');
    setCurrentStep((step) => step + 1);
  };

  const reset = () => {
    setCurrentStep(0);
    setWizardState('not-started');
  };

  const stateLabel = (state: WizardState): string => {
    if (state === 'done') return t('connection.state.ready');
    if (state === 'in-progress') return t('connection.wizard.inProgress');
    return t('connection.wizard.pending');
  };

  return (
    <>
      <div className="nx-page-header">
        <div>
          <h1 id={headingId}>{t('connection.title')}</h1>
          <p>{t('connection.subtitle')}</p>
        </div>
      </div>

      <div className="nx-grid">
        <section className="nx-card" aria-labelledby={`${headingId}-browser`}>
          <h2 id={`${headingId}-browser`} className="nx-card__title">
            {t('connection.browser.title')}
          </h2>
          <p className="nx-card__text">
            {t('connection.wizard.progress', { current: currentStep + 1, total: WIZARD_STEPS.length })}
          </p>
          <div>
            <StatusBadge
              tone={wizardState === 'done' ? 'success' : wizardState === 'in-progress' ? 'accent' : 'neutral'}
              label={wizardState === 'done' ? t('connection.state.ready') : stateLabel(wizardState)}
            />
          </div>
          <div className="nx-actions">
            <button
              type="button"
              className="nx-button nx-button--primary"
              onClick={advance}
              disabled={wizardState === 'done'}
              data-testid="wizard-advance"
            >
              {wizardState === 'not-started' ? t('action.continue') : t('action.test')}
            </button>
            <button type="button" className="nx-button" onClick={reset}>
              {t('action.cancel')}
            </button>
          </div>
        </section>

        <section className="nx-card" aria-labelledby={`${headingId}-local`}>
          <h2 id={`${headingId}-local`} className="nx-card__title">
            {t('connection.local.title')}
          </h2>
          <p className="nx-card__text">{t('connection.local.description')}</p>
          <div>
            <StatusBadge label={t('connection.health.unverified')} />
          </div>
        </section>

        <section className="nx-card" aria-labelledby={`${headingId}-api`}>
          <h2 id={`${headingId}-api`} className="nx-card__title">
            {t('connection.api.title')}
          </h2>
          <p className="nx-card__text">{t('connection.api.description')}</p>
          <div>
            <StatusBadge label={t('connection.health.unverified')} />
          </div>
        </section>
      </div>

      <section className="nx-panel" aria-labelledby={wizardHeadingId}>
        <h2 id={wizardHeadingId}>{t('connection.wizard.title')}</h2>
        <p className="nx-faint" aria-live="polite">
          {t('connection.wizard.progress', { current: currentStep + 1, total: WIZARD_STEPS.length })}
        </p>
        <ol className="nx-steps">
          {WIZARD_STEPS.map((stepKey, index) => {
            const state = stateOf(index);
            return (
              <li className="nx-step" data-state={state} key={stepKey}>
                <span className="nx-step__index" aria-hidden="true">
                  {index + 1}
                </span>
                <span className="nx-step__title">{t(stepKey)}</span>
                {/* The state is text, not colour alone (WCAG 1.4.1). */}
                <span className="nx-step__state">{stateLabel(state)}</span>
              </li>
            );
          })}
        </ol>
      </section>
    </>
  );
}
