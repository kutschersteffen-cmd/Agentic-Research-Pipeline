/** Sub-tab ids that were merged away; old links and bookmarks still land somewhere sensible. */
const LEGACY_SUB_TABS: Record<string, string> = { pivot: "dashboards", superset: "dashboards", genbi: "dashboards" };

/** The sub-tab to open for a route param: a known id, a legacy id's replacement, else the first tab (Dashboards). */
export function resolveSubTab<T extends string>(initialSub: string | undefined, tabs: readonly { id: T }[]): T {
  const id = initialSub === undefined ? undefined : (LEGACY_SUB_TABS[initialSub] ?? initialSub);
  return tabs.find((t) => t.id === id)?.id ?? tabs[0].id;
}

/** Risk Monitoring sub-tabs. */
export const SUB_TABS = [
  { id: "dashboards", label: "Dashboards (Superset)" },
  { id: "monitoring", label: "Monitoring & Alerts" },
  { id: "profiles", label: "Company Profiles" },
  { id: "ask", label: "Ask the Portfolio" },
  { id: "holdings", label: "Holdings Intake" },
] as const;

/** The sub-tab Risk Monitoring opens on. A route with no sub-tab opens Monitoring & Alerts, which works on a
 * server without Superset; a named, legacy or unknown id goes where resolveSubTab sends it. */
export function openingSubTab(initialSub: string | undefined): (typeof SUB_TABS)[number]["id"] {
  return initialSub ? resolveSubTab(initialSub, SUB_TABS) : "monitoring";
}
