// Sidebar, hubs and retired routes: pure data and rules, so they are testable
// without rendering App. Ids are App's tab ids.

/** The sidebar, top to bottom. Every other screen is reached from a workspace
 * page, a hub tab, Start or the command palette. */
export const NAV_GROUPS: { label: string | null; ids: readonly string[] }[] = [
  { label: null, ids: ["home"] },
  { label: "Needs you", ids: ["review"] },
  { label: "Workspaces", ids: ["stewardiq", "argus", "transitionIntel", "rdLab", "dataHub"] },
  { label: "Output", ids: ["reporting"] },
  { label: null, ids: ["arcade"] },
];

/** Screens that share a tab strip above the page. Every id keeps its own
 * route, so deep links and Processes steps still land. */
export const HUBS: { label: string; tabs: [string, string][] }[] = [
  { label: "Library", tabs: [["library", "Data Library"], ["search", "Search"]] },
  { label: "Runs", tabs: [["history", "Run history"], ["backgroundAgents", "Standing agents"]] },
];

// Removed screens and the screen that now does their job.
const RETIRED: [string, string][] = [
  ["dashboard", "#/home"],
  ["tape", "#/review"],
  ["identity", "#/extraction/identify"],
  ["discovery", "#/extraction/documents"],
];

/** Where an old link to a removed screen (or any path under it) lands, else null. */
export function redirectHash(hash: string): string | null {
  const hit = RETIRED.find(([id]) => hash === `#/${id}` || hash.startsWith(`#/${id}/`));
  return hit ? hit[1] : null;
}

/** The sidebar ids marked current while `active` is open: the link itself, or
 * the sidebar entry of the hub that holds it. */
export function currentNavIds(active: string): string[] {
  return NAV_GROUPS.flatMap((g) => g.ids).filter(
    (id) => id === active || HUBS.some((h) => h.tabs[0][0] === id && h.tabs.some(([t]) => t === active)),
  );
}

/** The waiting-count badge on a sidebar link. */
export const navCount = (id: string, waiting: { review: number } | null): number =>
  id === "review" ? (waiting?.review ?? 0) : 0;
