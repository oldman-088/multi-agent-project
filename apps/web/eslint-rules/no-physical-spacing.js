/**
 * ESLint rule: physical-direction classes are banned — use CSS logical
 * properties (ms/me/ps/pe/start/end) so EN (LTR), AR (RTL) and FA (RTL) stay
 * in parity (Section 8.2 of docs/SPEC.md). Fails on ml-/mr-/pl-/pr-/left-/
 * right-/text-left/text-right, including variants like hover:ml-2.
 */

const PHYSICAL_CLASS = /^(?:ml|mr|pl|pr)(?:-|$)|^(?:left|right)(?:-|$)|^text-(?:left|right)$/;

/** Inline style properties with physical direction meaning. */
const PHYSICAL_STYLE_PROPS = new Set([
  'marginLeft',
  'marginRight',
  'paddingLeft',
  'paddingRight',
  'left',
  'right',
]);

function checkToken(token, report) {
  for (const segment of token.split(':')) {
    if (PHYSICAL_CLASS.test(segment)) {
      report(segment);
      return;
    }
  }
}

/** Checks inline `style={{ … }}` objects for physical direction properties. */
function checkStyleObject(node, report) {
  if (!node || node.type !== 'ObjectExpression') {
    return;
  }
  for (const property of node.properties) {
    if (property.type !== 'Property') {
      continue;
    }
    const key =
      property.key.type === 'Identifier'
        ? property.key.name
        : property.key.type === 'Literal'
          ? property.key.value
          : undefined;
    if (typeof key === 'string' && PHYSICAL_STYLE_PROPS.has(key)) {
      report(property.key, key);
    }
  }
}

/** @type {import('eslint').Rule.RuleModule} */
export default {
  meta: {
    type: 'problem',
    docs: {
      description:
        'forbid physical-direction classes/styles; use CSS logical properties (SPEC 8.2)',
    },
    schema: [],
    messages: {
      physicalClass:
        "Physical-direction class '{{token}}'. Use logical properties instead: ms-/me-/ps-/pe-/start-/end- (SPEC 8.2).",
      physicalStyleProp:
        "Physical-direction style property '{{token}}'. Use marginInline*/paddingInline*/insetInline* instead (SPEC 8.2).",
    },
  },
  create(context) {
    function reportAt(node, messageId, token) {
      context.report({ node, messageId, data: { token } });
    }

    function checkString(value, node) {
      for (const token of value.split(/\s+/)) {
        if (token) {
          checkToken(token, (tok) => reportAt(node, 'physicalClass', tok));
        }
      }
    }

    return {
      // Covers string literals everywhere, including className="…" attributes.
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
      JSXAttribute(node) {
        if (node.name.name === 'style' && node.value) {
          const expression =
            node.value.type === 'JSXExpressionContainer' ? node.value.expression : node.value;
          checkStyleObject(expression, (target, token) =>
            reportAt(target, 'physicalStyleProp', token),
          );
        }
      },
    };
  },
};
