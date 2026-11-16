import { useEffect, useRef, useState } from "react";

/** A button and its popover (not a menu role): focus moves in on open; Esc inside, a press outside, or Tab out
 * of the wrapper closes it; a navigation closes it without moving focus. Shared by the top bar's menus. */
export function useDisclosure() {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const pop = popRef.current;
    const wrap = wrapRef.current;
    pop?.querySelector<HTMLElement>("input, button, a, select, [tabindex]")?.focus();
    const close = (refocus: boolean) => {
      setOpen(false);
      if (refocus) buttonRef.current?.focus();
    };
    // Only while focus is in the menu: Esc in the palette or the Ask panel belongs to them.
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && wrap?.contains(document.activeElement)) close(true);
    };
    const onDown = (e: PointerEvent) => {
      if (wrap?.contains(e.target as Node)) return;
      setOpen(false);
      // After the press's own focus change: refocus the button only if the press focused nothing else.
      setTimeout(() => {
        if (!document.activeElement?.matches("input, textarea, select, button, a[href], [tabindex]:not([tabindex='-1'])")) buttonRef.current?.focus();
      });
    };
    // Tab (or Shift+Tab) out of the menu and its button: close it and let focus move on.
    const onFocusOut = (e: FocusEvent) => {
      const to = e.relatedTarget as Node | null;
      if (to && !wrap?.contains(to)) setOpen(false);
    };
    const onHash = () => close(false);
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    wrap?.addEventListener("focusout", onFocusOut);
    window.addEventListener("hashchange", onHash);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
      wrap?.removeEventListener("focusout", onFocusOut);
      window.removeEventListener("hashchange", onHash);
    };
  }, [open]);

  return { open, setOpen, buttonRef, popRef, wrapRef };
}
