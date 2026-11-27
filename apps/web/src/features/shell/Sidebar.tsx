import { Home } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router-dom';
import { cn } from '../../lib/utils';

/** Primary navigation. Only screens that exist appear here (Section 8.3). */
export function Sidebar() {
  const { t } = useTranslation();

  return (
    <nav
      aria-label={t('shell.mainNav')}
      className="hidden w-48 shrink-0 border-e border-nx-border bg-nx-surface p-2 md:block"
    >
      <ul className="flex flex-col gap-1">
        <li>
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2 rounded-nx-md px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus',
                isActive
                  ? 'bg-nx-accent/15 font-medium text-nx-accent'
                  : 'text-nx-fg-muted hover:bg-nx-surface-raised hover:text-nx-fg',
              )
            }
          >
            <Home className="h-4 w-4" aria-hidden="true" />
            {t('nav.home')}
          </NavLink>
        </li>
      </ul>
    </nav>
  );
}
