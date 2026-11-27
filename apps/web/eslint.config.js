import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import noHardcodedColors from './eslint-rules/no-hardcoded-colors.js';
import noPhysicalSpacing from './eslint-rules/no-physical-spacing.js';

/** Local plugin enforcing the GUI rules of Section 8 (tokens + RTL). */
const nxGuiPlugin = {
  rules: {
    'no-hardcoded-colors': noHardcodedColors,
    'no-physical-spacing': noPhysicalSpacing,
  },
};

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage'] },
  {
    files: ['**/*.js'],
    extends: [js.configs.recommended],
    languageOptions: {
      globals: globals.node,
      sourceType: 'module',
    },
  },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      nx: nxGuiPlugin,
    },
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.node },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // Section 8.1 / 8.2 GUI rules — fail the build.
      'nx/no-hardcoded-colors': 'error',
      'nx/no-physical-spacing': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
    },
  },
  {
    // Test fixtures must be able to contain the very tokens the rules ban
    // (eslint-rules.test.ts lints bad snippets on purpose).
    files: ['**/*.test.{ts,tsx}', 'eslint-rules/**'],
    rules: {
      'nx/no-hardcoded-colors': 'off',
      'nx/no-physical-spacing': 'off',
    },
  },
);
