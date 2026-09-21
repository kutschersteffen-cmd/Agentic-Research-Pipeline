import { useCallback, useMemo, useSyncExternalStore } from "react";

/** Hash routing, no dependency and no server config: nginx keeps serving
 *  index.html for the one path it already knows about. A destination is
 *  `#/<tab>[/<sub-tab>][?params]`, so every view in the app is a link that
 *  survives a refresh, a back button and a paste into Slack. */
export interface Route {
  tab: string;
  sub: string | null;
  params: URLSearchParams;
}

export type Params = Record<string, string | number | null | undefined>;

const CHANGED = "arp:routechange";

function currentHash(): string {
  return window.location.hash.replace(/^#/, "") || "/";
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  window.addEventListener(CHANGED, onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
    window.removeEventListener(CHANGED, onChange);
  };
}

export function parseHash(hash: string): Route {
  const [path, query = ""] = hash.split("?");
  const [, tab = "", sub = ""] = path.split("/");
  return { tab, sub: sub || null, params: new URLSearchParams(query) };
}

export function buildHash(tab: string, opts: { sub?: string | null; params?: Params } = {}): string {
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(opts.params ?? {})) {
    if (v !== null && v !== undefined && v !== "") query.set(k, String(v));
  }
  const path = opts.sub ? `/${tab}/${opts.sub}` : `/${tab}`;
  const q = query.toString();
  return `#${path}${q ? `?${q}` : ""}`;
}

/** The href for a destination -- nav items are real links, so the browser's
 *  own affordances (open in a new tab, copy link, middle click) work. */
export function href(tab: string, opts: { sub?: string | null; params?: Params } = {}): string {
  return buildHash(tab, opts);
}

export function navigate(tab: string, opts: { sub?: string | null; params?: Params; replace?: boolean } = {}): void {
  const hash = buildHash(tab, opts);
  if (opts.replace) {
    window.history.replaceState(null, "", hash);
    window.dispatchEvent(new Event(CHANGED));
  } else {
    window.location.hash = hash;
  }
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, currentHash, () => "/");
  return useMemo(() => parseHash(hash), [hash]);
}

/** A page's sub-tab, kept in the URL's second segment. Falls back to the
 *  page's default when the segment is missing or unknown, so a hand-edited
 *  link still lands somewhere sensible. */
export function useSubTab<T extends string>(tabs: readonly { id: T }[], fallback: T): [T, (id: T) => void] {
  const route = useRoute();
  const active = tabs.find((t) => t.id === route.sub)?.id ?? fallback;
  const tab = route.tab;
  const query = route.params.toString();
  const set = useCallback(
    (id: T) => navigate(tab, { sub: id, params: Object.fromEntries(new URLSearchParams(query)) }),
    [tab, query]
  );
  return [active, set];
}

/** A single query param, read from and written to the URL. Filters go
 *  through here so a filtered list is a link -- and they replace rather
 *  than push, so narrowing a list five times does not cost five presses of
 *  the back button to leave the page. */
export function useParam(name: string, fallback = ""): [string, (value: string | null) => void] {
  const route = useRoute();
  const value = route.params.get(name) ?? fallback;
  const { tab, sub } = route;
  const query = route.params.toString();
  const set = useCallback(
    (next: string | null) => {
      const params: Params = Object.fromEntries(new URLSearchParams(query));
      if (next) params[name] = next;
      else delete params[name];
      navigate(tab, { sub, params, replace: true });
    },
    [name, tab, sub, query]
  );
  return [value, set];
}
