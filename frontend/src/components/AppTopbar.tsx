import { useEffect, useId, type RefObject } from "react";
import { reviewBadge, workspaceMenuItems } from "../lib/workspaceCard";
import { workspaceOfRoute } from "../lib/processes";
import { useMe, useReviewer } from "../lib/reviewer";
import { useDisclosure } from "../lib/useDisclosure";
import { useHouseFlow, useRuns } from "../pages/ProcessHub";
import { ReviewerField } from "./ReviewerField";
import { SignedInAs } from "./SignedInAs";
import { ThemeSwitch } from "./ThemeSwitch";

const mac = /Mac|iPhone|iPad/.test(navigator.userAgent);

// The pixel "ARP" lockup, placed exactly where the landing header puts it (28px high, 32px in, 24px down).
const LOCKUP =
  "M14 2h10v10h-10zM38 2h10v10h-10zM2 14h10v10h-10zM50 14h10v10h-10zM2 26h10v10h-10zM14 26h10v10h-10zM26 26h10v10h-10zM38 26h10v10h-10zM50 26h10v10h-10zM2 38h10v10h-10zM50 38h10v10h-10zM2 50h10v10h-10zM50 50h10v10h-10zM74 2h10v10h-10zM86 2h10v10h-10zM98 2h10v10h-10zM110 2h10v10h-10zM74 14h10v10h-10zM122 14h10v10h-10zM74 26h10v10h-10zM86 26h10v10h-10zM98 26h10v10h-10zM110 26h10v10h-10zM74 38h10v10h-10zM110 38h10v10h-10zM74 50h10v10h-10zM122 50h10v10h-10zM146 2h10v10h-10zM158 2h10v10h-10zM170 2h10v10h-10zM182 2h10v10h-10zM146 14h10v10h-10zM194 14h10v10h-10zM146 26h10v10h-10zM158 26h10v10h-10zM170 26h10v10h-10zM182 26h10v10h-10zM146 38h10v10h-10zM146 50h10v10h-10z";

type Props = {
  active: string;
  canAsk: boolean;
  askOpen: boolean;
  askRef: RefObject<HTMLButtonElement | null>;
  reviewCount: number;
  onSearch: () => void;
  onAsk: () => void;
};

/** The workspaces with their state. Mounted only while the menu is open, so its polling stops when it closes. */
function WorkspaceLinks({ current }: { current: string }) {
  const { runs } = useRuns();
  const { flow } = useHouseFlow();
  return workspaceMenuItems(runs, flow, new Date()).map((i) => (
    <a key={i.href} href={i.href} aria-current={i.href === current ? "page" : undefined}>
      <span className="start-topbar-place">
        {i.label}
        <span className="start-topbar-purpose">{i.purpose}</span>
      </span>
      {i.tone && (
        <span className="start-topbar-tag">
          <span className={`hub-mark hub-mark-${i.tone}`} aria-hidden="true" />
          <span className={`hub-status-${i.tone}`}>{i.word}</span>
        </span>
      )}
    </a>
  ));
}

/** The top bar on every page but the landing page. Everything the old sidebar said about the person (reviewer
 * name, sign-in, theme) is in the user menu; the workspaces are in the Workspaces menu. */
export function AppTopbar({ active, canAsk, askOpen, askRef, reviewCount, onSearch, onAsk }: Props) {
  const me = useMe();
  const name = me?.name ?? "Account";
  const [reviewer, setReviewer] = useReviewer();
  // Signed in, the verified name is the reviewer: flows that still send the typed name (voting) record it.
  useEffect(() => {
    if (me && reviewer !== me.name) setReviewer(me.name);
  }, [me, reviewer, setReviewer]);
  const badge = reviewBadge(reviewCount);
  const user = useDisclosure();
  const spaces = useDisclosure();
  const userPopId = useId();
  const spacesPopId = useId();
  const currentSpace = active === "home" ? "#/home" : `#/${workspaceOfRoute(window.location.hash) ?? ""}`;

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
          <div ref={spaces.wrapRef} className="start-topbar-spaces">
            <button
              ref={spaces.buttonRef}
              type="button"
              className="start-topbar-spaces-btn"
              aria-expanded={spaces.open}
              aria-controls={spacesPopId}
              onClick={() => spaces.setOpen(!spaces.open)}
            >
              Workspaces
              <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
                <path d="M1 3h8L5 7.5z" />
              </svg>
            </button>
            <div ref={spaces.popRef} id={spacesPopId} className="start-topbar-pop start-topbar-spaces-pop" hidden={!spaces.open}>
              {spaces.open && <WorkspaceLinks current={currentSpace} />}
            </div>
          </div>
          <a href="#/review" aria-current={active === "review" ? "page" : undefined}>
            Review Queue
            {badge && (
              <span className="nav-count" title={badge.title} aria-label={badge.title}>
                {/* "items" hides on a phone so the badge fits the second row; the label still says it. */}
                {badge.text.split(" ")[0]}
                <span className="nav-count-word"> {badge.text.split(" ").slice(1).join(" ")}</span>
              </span>
            )}
          </a>
          <a href="#/reporting" aria-current={active === "reporting" ? "page" : undefined}>
            Reports
          </a>
          <div ref={user.wrapRef} className="start-topbar-user">
            <button
              ref={user.buttonRef}
              type="button"
              className="start-topbar-me"
              aria-label={name}
              aria-expanded={user.open}
              aria-controls={userPopId}
              onClick={() => user.setOpen(!user.open)}
            >
              <span className="start-topbar-avatar" aria-hidden="true">
                {name.slice(0, 1).toUpperCase()}
              </span>
            </button>
            <div ref={user.popRef} id={userPopId} className="start-topbar-pop" hidden={!user.open}>
              {!me && <ReviewerField hint={false} />}
              <SignedInAs />
              <ThemeSwitch />
              <a href="#/arcade" onClick={() => user.setOpen(false)}>
                Arcade
              </a>
            </div>
          </div>
        </nav>
      </div>
    </header>
  );
}
