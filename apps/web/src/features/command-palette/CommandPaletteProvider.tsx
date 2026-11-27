import { useCallback, useEffect, useMemo, useState, type PropsWithChildren } from 'react';
import { CommandPaletteContext } from './command-palette-context';

/**
 * Holds the command palette open state and registers the global
 * Ctrl/Cmd+K shortcut (Section 8.3-J: command palette skeleton).
 */
export function CommandPaletteProvider({ children }: PropsWithChildren) {
  const [isOpen, setIsOpen] = useState(false);

  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);
  const toggle = useCallback(() => setIsOpen((current) => !current), []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setIsOpen((current) => !current);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const value = useMemo(
    () => ({ isOpen, open, close, toggle }),
    [isOpen, open, close, toggle],
  );

  return (
    <CommandPaletteContext.Provider value={value}>{children}</CommandPaletteContext.Provider>
  );
}
