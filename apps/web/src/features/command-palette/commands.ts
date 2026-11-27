import type { NavigateFunction } from 'react-router-dom';
import { SUPPORTED_LANGUAGES, type Language } from '../../lib/direction';

export interface Command {
  id: string;
  label: string;
  keywords: string[];
  run: () => void;
}

interface BuildCommandsOptions {
  t: (key: string) => string;
  navigate: NavigateFunction;
  currentLanguage: Language;
  setLanguage: (language: Language) => void;
  toggleTheme: () => void;
}

/**
 * Builds the palette command list. Structural skeleton only (Phase 1): every
 * command here must actually work — navigation, theme and language switching.
 */
export function buildCommands({
  t,
  navigate,
  currentLanguage,
  setLanguage,
  toggleTheme,
}: BuildCommandsOptions): Command[] {
  const languageCommands: Command[] = SUPPORTED_LANGUAGES.filter(
    (language) => language !== currentLanguage,
  ).map((language) => {
    // Locale keys use capital-first suffixes: setLanguageAr, setLanguageEn, setLanguageFa.
    const suffix = language.charAt(0).toUpperCase() + language.slice(1);
    return {
      id: `set-language-${language}`,
      label: t(`palette.commands.setLanguage${suffix}`),
      keywords: ['language', 'lang', language, 'لغة', 'زبان'],
      run: () => setLanguage(language),
    };
  });

  return [
    {
      id: 'go-home',
      label: t('palette.commands.goHome'),
      keywords: ['home', 'go', 'navigate', 'الرئيسية', 'صفحه اصلی'],
      run: () => navigate('/'),
    },
    {
      id: 'go-agents',
      label: t('palette.commands.goAgents'),
      keywords: ['agents', 'agent', 'go', 'navigate', 'الوكلاء', 'وكلاء', 'عوامل', 'نمایندگان'],
      run: () => navigate('/agents'),
    },
    {
      id: 'go-chat',
      label: t('palette.commands.goChat'),
      keywords: ['chat', 'conversation', 'message', 'go', 'navigate', 'الدردشة', 'محادثه', 'گفتگو'],
      run: () => navigate('/chat'),
    },
    {
      id: 'go-connections',
      label: t('palette.commands.goConnections'),
      keywords: [
        'connections',
        'bridge',
        'pairing',
        'devices',
        'go',
        'navigate',
        'الاتصالات',
        'الجسر',
        'اتصال',
        'اتصالات',
      ],
      run: () => navigate('/connections'),
    },
    {
      id: 'toggle-theme',
      label: t('palette.commands.toggleTheme'),
      keywords: ['theme', 'dark', 'light', 'toggle', 'مظهر', 'پوسته'],
      run: toggleTheme,
    },
    ...languageCommands,
  ];
}
