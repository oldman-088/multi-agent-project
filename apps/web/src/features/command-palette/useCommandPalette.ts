import { useContext } from 'react';
import { CommandPaletteContext, type CommandPaletteContextValue } from './command-palette-context';

export function useCommandPalette(): CommandPaletteContextValue {
  const value = useContext(CommandPaletteContext);
  if (!value) {
    throw new Error('useCommandPalette must be used within a CommandPaletteProvider');
  }
  return value;
}
