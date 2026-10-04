import { useEffect } from "react";

export type CardHandlers = Partial<Record<"a" | "c" | "r", (card: HTMLElement) => void>>;
/** Returns false when the key did nothing (no default to prevent). */
type KeyHandler = (card: HTMLElement | null) => boolean | void;

const IGNORE_INSIDE = "input, textarea, select, [contenteditable], dialog";

/** J / K move focus between the cards matching `selector`; the optional A / C / R
 * handlers get the card that holds focus. */
export function cardKeyHandlers(selector: string, handlers: CardHandlers = {}): Record<string, KeyHandler> {
  const move = (down: boolean): KeyHandler => () => {
    const cards = [...document.querySelectorAll<HTMLElement>(selector)];
    const at = cards.indexOf(document.activeElement as HTMLElement);
    const next = cards[down ? at + 1 : Math.max(at - 1, 0)];
    if (!next) return false;
    next.focus();
    next.scrollIntoView({ block: "start", behavior: "smooth" });
  };
  const out: Record<string, KeyHandler> = { j: move(true), k: move(false) };
  for (const [k, h] of Object.entries(handlers)) out[k] = (card) => (card && h ? h(card) : false);
  return out;
}

/** Runs the handler for `e.key`, unless a modifier is held or the key was typed
 * inside a field or dialog. True when it handled the key. */
export function dispatchCardKey(e: KeyboardEvent, handlers: Record<string, KeyHandler>, card: HTMLElement | null): boolean {
  const h = Object.hasOwn(handlers, e.key) ? handlers[e.key] : undefined;
  if (e.ctrlKey || e.metaKey || e.altKey || !h) return false;
  if ((e.target as HTMLElement).closest(IGNORE_INSIDE)) return false;
  return h(card) !== false;
}

/** J / K move focus between the cards matching `selector` (give them
 * tabIndex={-1}). Moving only: deciding stays a click, so a stray key can
 * never approve or cast anything. The optional A / C / R `handlers` may open
 * and focus a decision form, never submit one. Pass a stable `handlers` object. */
export function useCardKeys(selector: string, handlers?: CardHandlers) {
  useEffect(() => {
    const keys = cardKeyHandlers(selector, handlers);
    const onKey = (e: KeyboardEvent) => {
      const card = (document.activeElement as HTMLElement | null)?.closest<HTMLElement>(selector) ?? null;
      if (dispatchCardKey(e, keys, card)) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selector, handlers]);
}

/** After a decision on `card`, keep the keyboard where the work is: the next
 * card in `selector` order, else `fallback`. The next card is a different item,
 * so it stays mounted while the decided one re-renders. */
export function focusNextCard(card: HTMLElement | null, selector: string, fallback?: string) {
  const cards = [...document.querySelectorAll<HTMLElement>(selector)];
  const next = card ? cards[cards.indexOf(card) + 1] : undefined;
  (next ?? (fallback ? document.querySelector<HTMLElement>(fallback) : null))?.focus();
}
