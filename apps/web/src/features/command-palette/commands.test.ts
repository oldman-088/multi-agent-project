import { describe, expect, it, vi } from 'vitest';
import { buildCommands } from './commands';

const t = (key: string) => key;
const navigate = vi.fn();
const setLanguage = vi.fn();
const toggleTheme = vi.fn();

describe('buildCommands (SPEC 8.3-J palette)', () => {
  it('returns 7 commands: 4 navigation targets, theme toggle and the two non-current languages', () => {
    const commands = buildCommands({
      t,
      navigate,
      currentLanguage: 'ar',
      setLanguage,
      toggleTheme,
    });

    expect(commands.map((command) => command.id)).toEqual([
      'go-home',
      'go-agents',
      'go-chat',
      'go-connections',
      'toggle-theme',
      'set-language-en',
      'set-language-fa',
    ]);
  });

  it('labels resolve against the i18n key set (setLanguage{Ar,En,Fa})', () => {
    const commands = buildCommands({
      t,
      navigate,
      currentLanguage: 'ar',
      setLanguage,
      toggleTheme,
    });

    expect(commands[0]?.label).toBe('palette.commands.goHome');
    expect(commands[1]?.label).toBe('palette.commands.goAgents');
    expect(commands[2]?.label).toBe('palette.commands.goChat');
    expect(commands[3]?.label).toBe('palette.commands.goConnections');
    expect(commands[4]?.label).toBe('palette.commands.toggleTheme');
    expect(commands[5]?.label).toBe('palette.commands.setLanguageEn');
    expect(commands[6]?.label).toBe('palette.commands.setLanguageFa');
  });

  it('every command actually executes', () => {
    const commands = buildCommands({
      t,
      navigate,
      currentLanguage: 'ar',
      setLanguage,
      toggleTheme,
    });

    for (const command of commands) {
      command.run();
    }

    expect(navigate).toHaveBeenCalledWith('/');
    expect(navigate).toHaveBeenCalledWith('/agents');
    expect(navigate).toHaveBeenCalledWith('/chat');
    expect(navigate).toHaveBeenCalledWith('/connections');
    expect(toggleTheme).toHaveBeenCalledTimes(1);
    expect(setLanguage).toHaveBeenCalledWith('en');
    expect(setLanguage).toHaveBeenCalledWith('fa');
    expect(setLanguage).not.toHaveBeenCalledWith('ar');
  });

  it('excludes the current language from the command list', () => {
    const commands = buildCommands({
      t,
      navigate,
      currentLanguage: 'fa',
      setLanguage,
      toggleTheme,
    });

    expect(commands.map((command) => command.id)).toEqual([
      'go-home',
      'go-agents',
      'go-chat',
      'go-connections',
      'toggle-theme',
      'set-language-ar',
      'set-language-en',
    ]);
  });
});
