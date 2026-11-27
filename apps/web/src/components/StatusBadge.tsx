/**
 * Status badge with a text label and a colour that always accompanies the text
 * (never colour alone — WCAG 1.4.1).
 */
export type BadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

export interface StatusBadgeProps {
  readonly label: string;
  readonly tone?: BadgeTone;
}

const TONE_CLASS: Readonly<Record<BadgeTone, string>> = {
  neutral: 'nx-badge',
  accent: 'nx-badge nx-badge--accent',
  success: 'nx-badge nx-badge--success',
  warning: 'nx-badge nx-badge--warning',
  danger: 'nx-badge nx-badge--danger',
};

export function StatusBadge({ label, tone = 'neutral' }: StatusBadgeProps) {
  return <span className={TONE_CLASS[tone]}>{label}</span>;
}
