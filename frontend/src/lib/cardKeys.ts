import { useEffect } from "react";

/** J / K move focus between the cards matching `selector` (give them
 * tabIndex={-1}). Moving only: deciding stays a click, so a stray key can
 * never approve or cast anything. */
export function useCardKeys(selector: string) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || (e.key !== "j" && e.key !== "k")) return;
      if ((e.target as HTMLElement).closest("input, textarea, select, [contenteditable], dialog")) return;
      const cards = [...document.querySelectorAll<HTMLElement>(selector)];
      const at = cards.indexOf(document.activeElement as HTMLElement);
      const next = cards[e.key === "j" ? at + 1 : Math.max(at - 1, 0)];
      if (!next) return;
      e.preventDefault();
      next.focus();
      next.scrollIntoView({ block: "start", behavior: "smooth" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selector]);
}
