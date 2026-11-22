import { useState } from "react";
import { HUBS } from "../lib/nav";
import { WORKSPACES, moreLinks, rowLinks, workspaceOfRoute } from "../lib/processes";
import { useDisclosure } from "../lib/useDisclosure";

const isAt = (hash: string, href: string) => hash === href || hash.startsWith(href + "/");

/** Under the top bar inside a workspace: where you are, and the workspace's screens one click away. */
export function WorkspaceRow({ hash: at0 }: { hash: string }) {
  // A hub's other tabs count as its first tab (#/emergingThemes is part of Themes).
  const hub = HUBS.find((h) => h.tabs.slice(1).some(([t]) => isAt(at0, `#/${t}`)));
  const hash = hub ? `#/${hub.tabs[0][0]}` : at0;
  const id = workspaceOfRoute(hash);
  const w = WORKSPACES.find((x) => x.id === id);
  const more = useDisclosure();
  // The row scrolls sideways on a phone, so the menu is placed in the viewport, not inside the row.
  const [at, setAt] = useState<{ left: number; top: number } | null>(null);
  if (!w) return null;
  const links = rowLinks(w);
  const extra = moreLinks(w);
  // The current screen is the longest href the hash equals or extends, of the row's and the More menu's; else the workspace itself.
  const current = [...links.slice(1), ...extra].reduce<string | null>((best, [href]) => (isAt(hash, href) && href.length > (best?.length ?? 0) ? href : best), null) ?? links[0][0];
  const inMore = extra.some(([href]) => href === current);
  return (
    <nav className="ws-row" aria-label={`${w.short ?? w.name} screens`}>
      {links.map(([href, label], i) => (
        <a key={href} href={href} className={i === 0 ? "ws-row-name" : undefined} aria-current={href === current ? "page" : undefined}>
          {label}
        </a>
      ))}
      {extra.length > 0 && (
        <div ref={more.wrapRef} className="ws-row-more">
          <button
            ref={more.buttonRef}
            type="button"
            className="ws-row-more-btn"
            aria-expanded={more.open}
            aria-current={inMore ? "page" : undefined}
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              setAt({ left: Math.max(16, Math.min(r.left, window.innerWidth - 256)), top: r.bottom + 4 });
              more.setOpen(!more.open);
            }}
          >
            More
            <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
              <path d="M1 3h8L5 7.5z" />
            </svg>
          </button>
          <div ref={more.popRef} className="ws-row-more-pop" hidden={!more.open} style={at ? { left: at.left, top: at.top } : undefined}>
            {extra.map(([href, label]) => (
              <a key={href} href={href} aria-current={href === current ? "page" : undefined}>
                {label}
              </a>
            ))}
          </div>
        </div>
      )}
    </nav>
  );
}
