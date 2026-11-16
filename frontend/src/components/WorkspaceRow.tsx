import { WORKSPACES, rowLinks, workspaceOfRoute } from "../lib/processes";

/** Under the top bar inside a workspace: where you are, and the workspace's screens one click away. */
export function WorkspaceRow({ hash }: { hash: string }) {
  const id = workspaceOfRoute(hash);
  const w = WORKSPACES.find((x) => x.id === id);
  if (!w) return null;
  const links = rowLinks(w);
  // The current screen is the longest href the hash equals or extends; otherwise the workspace itself.
  const current = links.slice(1).reduce<string | null>((best, [href]) => ((hash === href || hash.startsWith(href + "/")) && href.length > (best?.length ?? 0) ? href : best), null) ?? links[0][0];
  return (
    <nav className="ws-row" aria-label={`${w.short ?? w.name} screens`}>
      {links.map(([href, label], i) => (
        <a key={href} href={href} className={i === 0 ? "ws-row-name" : undefined} aria-current={href === current ? "page" : undefined}>
          {label}
        </a>
      ))}
    </nav>
  );
}
