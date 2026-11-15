import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { reviewBadge } from "../lib/workspaceCard";
import { useMe } from "../lib/reviewer";
import { ReviewerField } from "./ReviewerField";
import { SignedInAs } from "./SignedInAs";
import { ThemeSwitch } from "./ThemeSwitch";

const mac = /Mac|iPhone|iPad/.test(navigator.userAgent);

// The pixel "ARP" lockup, placed exactly where the landing header puts it (28px high, 32px in, 24px down).
const LOCKUP =
  "M14 2h10v10h-10zM38 2h10v10h-10zM2 14h10v10h-10zM50 14h10v10h-10zM2 26h10v10h-10zM14 26h10v10h-10zM26 26h10v10h-10zM38 26h10v10h-10zM50 26h10v10h-10zM2 38h10v10h-10zM50 38h10v10h-10zM2 50h10v10h-10zM50 50h10v10h-10zM74 2h10v10h-10zM86 2h10v10h-10zM98 2h10v10h-10zM110 2h10v10h-10zM74 14h10v10h-10zM122 14h10v10h-10zM74 26h10v10h-10zM86 26h10v10h-10zM98 26h10v10h-10zM110 26h10v10h-10zM74 38h10v10h-10zM110 38h10v10h-10zM74 50h10v10h-10zM122 50h10v10h-10zM146 2h10v10h-10zM158 2h10v10h-10zM170 2h10v10h-10zM182 2h10v10h-10zM146 14h10v10h-10zM194 14h10v10h-10zM146 26h10v10h-10zM158 26h10v10h-10zM170 26h10v10h-10zM182 26h10v10h-10zM146 38h10v10h-10zM146 50h10v10h-10z";

type Props = {
  canAsk: boolean;
  askOpen: boolean;
  askRef: RefObject<HTMLButtonElement | null>;
  reviewCount: number;
  onSearch: () => void;
  onAsk: () => void;
};

/** The start page's top bar: it replaces the sidebar there. Everything the sidebar said about the person
 * (reviewer name, sign-in, theme) moves into the user menu, a disclosure popover. */
export function StartTopbar({ canAsk, askOpen, askRef, reviewCount, onSearch, onAsk }: Props) {
  const me = useMe();
  const name = me?.name ?? "Account";
  const badge = reviewBadge(reviewCount);
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const userRef = useRef<HTMLDivElement>(null);
  const popId = useId();

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) buttonRef.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    const pop = popRef.current;
    const user = userRef.current;
    pop?.querySelector<HTMLElement>("input, button, a, select, [tabindex]")?.focus();
    const onKey = (e: KeyboardEvent) => {
      // Only while focus is in the menu: Esc in the palette or the Ask panel belongs to them.
      if (e.key === "Escape" && user?.contains(document.activeElement)) close(true);
    };
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (pop?.contains(t) || buttonRef.current?.contains(t)) return;
      setOpen(false);
      // After the press's own focus change: refocus the button only if the press focused nothing else.
      setTimeout(() => {
        if (!document.activeElement?.matches("input, textarea, select, button, a[href], [tabindex]:not([tabindex='-1'])")) buttonRef.current?.focus();
      });
    };
    // Tab (or Shift+Tab) out of the menu and its button: close it and let focus move on.
    const onFocusOut = (e: FocusEvent) => {
      const to = e.relatedTarget as Node | null;
      if (to && !user?.contains(to)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    user?.addEventListener("focusout", onFocusOut);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
      user?.removeEventListener("focusout", onFocusOut);
    };
  }, [open]);

  return (
    <header className="start-topbar">
      <a className="start-topbar-brand" href="#/home" aria-label="ARP start">
        <svg className="start-topbar-lockup" viewBox="0 0 206 62" aria-hidden="true" focusable="false">
          <path fill="currentColor" d={LOCKUP} />
          <rect x="26" y="2" width="10" height="10" fill="var(--brand-apex)" />
        </svg>
      </a>
      <button type="button" className="start-topbar-search" aria-keyshortcuts="Control+K Meta+K" onClick={onSearch}>
        <svg className="start-topbar-search-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true">
          <circle cx="7" cy="7" r="4.5" />
          <path d="M10.5 10.5 14 14" strokeLinecap="round" />
        </svg>
        <span className="start-topbar-search-label">Search or jump to…</span>
        <kbd aria-hidden="true">{mac ? "⌘K" : "Ctrl K"}</kbd>
      </button>
      <div className="start-topbar-end">
        {canAsk && (
          <button ref={askRef} type="button" className="start-topbar-ask" aria-keyshortcuts="Control+J Meta+J" aria-expanded={askOpen} onClick={onAsk}>
            Ask ARP <kbd aria-hidden="true">{mac ? "⌘J" : "Ctrl J"}</kbd>
          </button>
        )}
        <nav className="start-topbar-nav" aria-label="Main">
          <a href="#/review">
            Review Queue
            {badge && (
              <span className="nav-count" title={badge.title} aria-label={badge.title}>
                {badge.text}
              </span>
            )}
          </a>
          <a href="#/reporting">Reports</a>
          <div ref={userRef} className="start-topbar-user">
            <button
              ref={buttonRef}
              type="button"
              className="start-topbar-me"
              aria-label={name}
              aria-expanded={open}
              aria-controls={popId}
              onClick={() => (open ? close(false) : setOpen(true))}
            >
              <span className="start-topbar-avatar" aria-hidden="true">
                {name.slice(0, 1).toUpperCase()}
              </span>
            </button>
            <div ref={popRef} id={popId} className="start-topbar-pop" hidden={!open}>
              <ReviewerField hint={false} />
              <SignedInAs />
              <ThemeSwitch />
              <a href="#/arcade" onClick={() => setOpen(false)}>
                Arcade
              </a>
            </div>
          </div>
        </nav>
      </div>
    </header>
  );
}
