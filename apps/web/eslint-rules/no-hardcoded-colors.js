/**
 * ESLint rule: components must never use hard-coded palette classes
 * (bg-slate-950, text-white, …) or raw hex values — only --nx-* design-token
 * utilities (Section 8.1 of docs/SPEC.md).
 */

const PALETTE_COLORS = [
  'slate',
  'zinc',
  'neutral',
  'stone',
  'gray',
  'red',
  'orange',
  'amber',
  'yellow',
  'lime',
  'green',
  'emerald',
  'teal',
  'cyan',
  'sky',
  'blue',
  'indigo',
  'violet',
  'purple',
  'fuchsia',
  'pink',
  'rose',
  'white',
  'black',
];

const COLOR_PREFIXES = [
  'bg',
  'text',
  'border',
  'fill',
  'stroke',
  'ring',
  'outline',
  'divide',
  'placeholder',
  'from',
  'via',
  'to',
  'shadow',
  'decoration',
  'caret',
  'accent',
  'selection',
];

const COLOR_UTILITY = new RegExp(
  `^(?:${COLOR_PREFIXES.join('|')})-(?:${PALETTE_COLORS.join('|')})(?:-\\d{1,3})?(?:\\/\\d{1,3})?$`,
);
const ARBITRARY_HEX = /\[#[0-9a-fA-F]{3,8}\]/;
const BARE_HEX = /^#[0-9a-fA-F]{3,8}$/;

function checkToken(token, report) {
  if (ARBITRARY_HEX.test(token) || BARE_HEX.test(token)) {
    report(token, 'hardcodedHex');
    return;
  }
  // Strip variant prefixes (hover:, md:, focus-visible:, …) per segment.
  for (const segment of token.split(':')) {
    if (COLOR_UTILITY.test(segment)) {
      report(segment, 'hardcodedColor');
      return;
    }
  }
}

/** @type {import('eslint').Rule.RuleModule} */
export default {
  meta: {
    type: 'problem',
    docs: {
      description:
        'forbid hard-coded palette colors and raw hex values; use --nx-* design tokens (SPEC 8.1)',
    },
    schema: [],
    messages: {
      hardcodedColor:
        "Hard-coded palette class '{{token}}'. Use an --nx-* design-token utility instead (SPEC 8.1).",
      hardcodedHex:
        "Raw hex color '{{token}}'. Define it as an --nx-* token in tokens.css instead (SPEC 8.1).",
    },
  },
  create(context) {
    function reportAt(node, messageId, token) {
      context.report({ node, messageId, data: { token } });
    }

    function checkString(value, node) {
      for (const token of value.split(/\s+/)) {
        if (token) {
          checkToken(token, (tok, id) => reportAt(node, id, tok));
        }
      }
    }

    return {
      // Covers string literals everywhere, including className="…" attributes
      // and hex values inside style={{ color: '#…' }} objects.
      Literal(node) {
        if (typeof node.value === 'string') {
          checkString(node.value, node);
        }
      },
      TemplateElement(node) {
        const value = node.value.cooked;
        if (typeof value === 'string') {
          checkString(value, node);
        }
      },
    };
  },
};
