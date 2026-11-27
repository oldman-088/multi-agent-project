import { describe, expect, it } from 'vitest';
import { Linter } from 'eslint';
import noHardcodedColors from '../eslint-rules/no-hardcoded-colors.js';
import noPhysicalSpacing from '../eslint-rules/no-physical-spacing.js';

const linter = new Linter({ configType: 'flat' });

const config = [
  {
    files: ['**/*.tsx'],
    plugins: {
      nx: {
        rules: {
          'no-hardcoded-colors': noHardcodedColors,
          'no-physical-spacing': noPhysicalSpacing,
        },
      },
    },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module' as const,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      'nx/no-hardcoded-colors': 'error' as const,
      'nx/no-physical-spacing': 'error' as const,
    },
  },
];

function lint(code: string) {
  return linter.verify(code, config, 'fixture.tsx');
}

describe('nx/no-hardcoded-colors (SPEC 8.1)', () => {
  it('rejects hard-coded palette classes', () => {
    const messages = lint(`export const A = () => <div className="bg-slate-950 text-white" />;`);
    expect(messages).toHaveLength(2);
    expect(messages.map((m) => m.ruleId)).toEqual([
      'nx/no-hardcoded-colors',
      'nx/no-hardcoded-colors',
    ]);
    expect(messages[0]?.messageId).toBe('hardcodedColor');
  });

  it('rejects hard-coded palette classes behind variants', () => {
    const messages = lint(`export const A = () => <div className="hover:bg-red-500" />;`);
    expect(messages).toHaveLength(1);
    expect(messages[0]?.messageId).toBe('hardcodedColor');
  });

  it('rejects raw hex in className and in style objects', () => {
    expect(lint(`export const A = () => <div className="bg-[#123456]" />;`)[0]?.messageId).toBe(
      'hardcodedHex',
    );
    expect(
      lint(`export const A = () => <div style={{ color: '#ff0000' }} />;`)[0]?.messageId).toBe(
        'hardcodedHex',
      );
  });

  it('accepts --nx-* design-token utilities', () => {
    const messages = lint(
      `export const A = () => <div className="bg-nx-surface text-nx-fg border-nx-border" />;`,
    );
    expect(messages).toEqual([]);
  });
});

describe('nx/no-physical-spacing (SPEC 8.2)', () => {
  it('rejects ml-/mr-/pl-/pr- classes, including with variants', () => {
    const messages = lint(`export const A = () => <div className="ml-4 pr-2 hover:mr-1" />;`);
    expect(messages).toHaveLength(3);
    expect(messages.every((m) => m.ruleId === 'nx/no-physical-spacing')).toBe(true);
    expect(messages.every((m) => m.messageId === 'physicalClass')).toBe(true);
  });

  it('rejects left-/right- and text-left/text-right', () => {
    const messages = lint(
      `export const A = () => <div className="left-0 text-right inset-y-0" />;`,
    );
    const physical = messages.filter((m) => m.ruleId === 'nx/no-physical-spacing');
    expect(physical).toHaveLength(2); // right-0 and text-right
  });

  it('rejects physical style properties', () => {
    const messages = lint(`export const A = () => <div style={{ marginLeft: 4 }} />;`);
    expect(messages).toHaveLength(1);
    expect(messages[0]?.messageId).toBe('physicalStyleProp');
  });

  it('accepts logical properties (ms/me/ps/pe/start/end)', () => {
    const messages = lint(
      `export const A = () => <div className="ms-4 me-2 ps-3 pe-1 start-0 end-0 text-start" />;`,
    );
    expect(messages).toEqual([]);
  });
});
