// Sidebar, hubs and retired routes: pure data and rules, so they are testable
// without rendering App. Ids are App's tab ids.

/** The sidebar, top to bottom. Every other screen is reached from a workspace
 * page, a hub tab, Start or the command palette. */
/** Screens that share a tab strip above the page. Every id keeps its own
 * route, so deep links and Processes steps still land. */
export const HUBS: { label: string; tabs: [string, string][] }[] = [
  { label: "Library", tabs: [["library", "Data Library"], ["search", "Search"]] },
  { label: "Runs", tabs: [["history", "Run history"], ["plans", "Research plans"], ["backgroundAgents", "Standing agents"]] },
];

// Removed screens and the screen that now does their job.
const RETIRED: [string, string][] = [
  ["dashboard", "#/home"],
  ["tape", "#/review"],
  // The old Extraction screens: the Argus flow does their job (#/argus/new opens step 1 of a new flow).
  ["extraction", "#/argus"],
  ["argusUniverse", "#/argus/new"],
  ["identity", "#/argus/new"],
  ["discovery", "#/argus/new"],
  ["transitionPlan", "#/argus/new/transition_plan"],
];

/** Where an old link to a removed screen (or any path under it) lands, else null. */
export function redirectHash(hash: string): string | null {
  const hit = RETIRED.find(([id]) => hash === `#/${id}` || hash.startsWith(`#/${id}/`));
  return hit ? hit[1] : null;
}

/** Opening ARP with no page in the address (or #/welcome) lands on the landing page;
 * every other hash routes as before, so direct links keep working. */
export const entryTab = (hash: string): "welcome" | null =>
  ["", "#", "#/", "#/welcome"].includes(hash) ? "welcome" : null;

/** `#/<tab>[?query]/<param>...` split into its parts, each decoded. Only the tab segment's `?query` is split off
 * (e.g. #/refine?rfp=3); a later param keeps its own (a walkthrough's `?basis=`, see parseWalkthroughParams). */
export function splitHash(hash: string): { tab: string; params: string[]; query: URLSearchParams } {
  const [first = "", ...params] = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const q = first.indexOf("?");
  return { tab: q < 0 ? first : first.slice(0, q), params, query: new URLSearchParams(q < 0 ? "" : first.slice(q + 1)) };
}
