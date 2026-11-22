/** Sub-tab ids that were merged away; old links and bookmarks still land somewhere sensible. */
const LEGACY_SUB_TABS: Record<string, string> = { pivot: "dashboards", superset: "dashboards", genbi: "dashboards" };

/** The sub-tab to open for a route param: a known id, a legacy id's replacement, else the first tab (Dashboards). */
export function resolveSubTab<T extends string>(initialSub: string | undefined, tabs: readonly { id: T }[]): T {
  const id = initialSub === undefined ? undefined : (LEGACY_SUB_TABS[initialSub] ?? initialSub);
  return tabs.find((t) => t.id === id)?.id ?? tabs[0].id;
}

/** Risk Monitoring sub-tabs: every routable one (⌘K lists them all). */
export const SUB_TABS = [
  { id: "dashboards", label: "Dashboards" },
  { id: "monitoring", label: "Alerts" },
  { id: "profiles", label: "Company profiles" },
  { id: "ask", label: "Ask the Portfolio" },
  { id: "holdings", label: "Holdings Intake" },
] as const;

/** The tabs Risk Monitoring shows, in order. Ask the Portfolio and Holdings Intake open by link
 * (the search-or-ask box, "Load holdings") with no tab selected. */
export const SHOWN_SUB_TABS = ["monitoring", "dashboards", "profiles"] as const;

/** The sub-tab Risk Monitoring opens on. A route with no sub-tab opens Monitoring & Alerts, which works on a
 * server without Superset; a named, legacy or unknown id goes where resolveSubTab sends it. */
export function openingSubTab(initialSub: string | undefined): (typeof SUB_TABS)[number]["id"] {
  return initialSub ? resolveSubTab(initialSub, SUB_TABS) : "monitoring";
}
