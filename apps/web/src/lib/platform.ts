/** Platform helpers for the keyboard shortcut hint (Ctrl vs ⌘). */

export const IS_MAC_PLATFORM =
  typeof navigator !== 'undefined' && /mac|iphone|ipad|ipod/i.test(navigator.userAgent);

/** Human-readable shortcut label, e.g. "Ctrl+K" or "⌘K". */
export const MOD_KEY_LABEL = IS_MAC_PLATFORM ? '⌘K' : 'Ctrl+K';
