import { Bot, Home, MessagesSquare, PlugZap } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router-dom';
import { cn } from '../../lib/utils';

interface NavItem {
  to: string;
  labelKey: string;
  icon: LucideIcon;
  end?: boolean;
}

/** Primary navigation. Only screens that exist appear here (Section 8.3). */
const NAV_ITEMS: NavItem[] = [
  { to: '/', labelKey: 'nav.home', icon: Home, end: true },
  { to: '/agents', labelKey: 'nav.agents', icon: Bot },
  { to: '/chat', labelKey: 'nav.chat', icon: MessagesSquare },
  { to: '/connections', labelKey: 'nav.connections', icon: PlugZap },
];

export function Sidebar() {
  const { t } = useTranslation();

  return (
    <nav
      aria-label={t('shell.mainNav')}
      className="hidden w-48 shrink-0 border-e border-nx-border bg-nx-surface p-2 md:block"
    >
      <ul className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ to, labelKey, icon: Icon, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2 rounded-nx-md px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus',
                  isActive
                    ? 'bg-nx-accent/15 font-medium text-nx-accent'
                    : 'text-nx-fg-muted hover:bg-nx-surface-raised hover:text-nx-fg',
                )
              }
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {t(labelKey)}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
