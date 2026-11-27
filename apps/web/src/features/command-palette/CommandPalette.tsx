import { Command, Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../../components/ui/dialog';
import { cn } from '../../lib/utils';
import { useLanguage } from '../language/useLanguage';
import { useTheme } from '../theme/useTheme';
import { buildCommands, type Command as PaletteCommand } from './commands';
import { useCommandPalette } from './useCommandPalette';

const LISTBOX_ID = 'command-palette-listbox';

/**
 * Ctrl/Cmd+K palette. Phase 1 skeleton: structural shell + working commands
 * only (navigation, theme, language). No placeholder actions.
 */
export function CommandPalette() {
  const { t } = useTranslation();
  const { isOpen, close } = useCommandPalette();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const { toggleTheme } = useTheme();
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const commands = useMemo(
    () =>
      buildCommands({
        t,
        navigate,
        currentLanguage: language,
        setLanguage,
        toggleTheme,
      }),
    [t, navigate, language, setLanguage, toggleTheme],
  );

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return commands;
    }
    return commands.filter(
      (command) =>
        command.label.toLowerCase().includes(normalized) ||
        command.keywords.some((keyword) => keyword.toLowerCase().includes(normalized)),
    );
  }, [commands, query]);

  // Reset the palette each time it opens.
  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setActiveIndex(0);
    }
  }, [isOpen]);

  // Keep the active option inside the visible list.
  useEffect(() => {
    const active = document.getElementById(`command-option-${activeIndex}`);
    active?.scrollIntoView?.({ block: 'nearest' });
  }, [activeIndex, filtered.length]);

  const runCommand = (command: PaletteCommand) => {
    close();
    command.run();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % Math.max(filtered.length, 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex(
        (current) => (current - 1 + filtered.length) % Math.max(filtered.length, 1),
      );
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const command = filtered[activeIndex];
      if (command) {
        runCommand(command);
      }
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => (open ? undefined : close())}>
      <DialogContent
        className="max-w-xl p-0"
        containerClassName="items-start pt-[10vh]"
        showClose={false}
      >
        <DialogTitle className="sr-only">{t('palette.open')}</DialogTitle>
        <DialogDescription className="sr-only">{t('palette.placeholder')}</DialogDescription>
        <div className="flex items-center gap-2 border-b border-nx-border px-4">
          <Search className="h-4 w-4 shrink-0 text-nx-fg-muted" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-controls={LISTBOX_ID}
            aria-activedescendant={filtered.length > 0 ? `command-option-${activeIndex}` : undefined}
            aria-label={t('palette.placeholder')}
            className="h-12 w-full bg-transparent text-sm text-nx-fg placeholder:text-nx-fg-muted focus-visible:outline-none"
            placeholder={t('palette.placeholder')}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={onKeyDown}
          />
          <kbd className="hidden rounded-nx-sm border border-nx-border bg-nx-surface-raised px-1.5 py-0.5 font-mono text-[0.7rem] text-nx-fg-muted sm:block">
            Esc
          </kbd>
        </div>
        {filtered.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-nx-fg-muted">{t('palette.empty')}</p>
        ) : (
          <ul
            id={LISTBOX_ID}
            role="listbox"
            aria-label={t('palette.open')}
            className="max-h-80 overflow-y-auto p-2"
          >
            {filtered.map((command, index) => (
              <li
                key={command.id}
                id={`command-option-${index}`}
                role="option"
                aria-selected={index === activeIndex}
                className={cn(
                  'flex cursor-pointer items-center gap-3 rounded-nx-md px-3 py-2 text-sm',
                  index === activeIndex
                    ? 'bg-nx-accent/15 font-medium text-nx-fg'
                    : 'text-nx-fg-muted hover:bg-nx-surface-raised hover:text-nx-fg',
                )}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => runCommand(command)}
              >
                <Command className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{command.label}</span>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}
