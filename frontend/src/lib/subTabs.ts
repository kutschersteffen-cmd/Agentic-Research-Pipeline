/** Sub-tab ids that were merged away; old links and bookmarks still land somewhere sensible. */
const LEGACY_SUB_TABS: Record<string, string> = { pivot: "dashboards", superset: "dashboards", genbi: "dashboards" };

/** The sub-tab to open for a route param: a known id, a legacy id's replacement, else the first tab. */
export function resolveSubTab<T extends string>(initialSub: string | undefined, tabs: readonly { id: T }[]): T {
  const id = initialSub === undefined ? undefined : (LEGACY_SUB_TABS[initialSub] ?? initialSub);
  return tabs.find((t) => t.id === id)?.id ?? tabs[0].id;
}
