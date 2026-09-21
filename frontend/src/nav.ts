/** The app's destinations, in one place: the sidebar, the command palette
 *  and each page's sub-tabs all read from here, so a new view cannot be
 *  reachable from one of them and invisible to the others. */

export const TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "search", label: "Search" },
  { id: "theme", label: "Thematic Universe" },
  { id: "taxonomy", label: "Taxonomy Library" },
  { id: "emergingThemes", label: "Emerging Themes" },
  { id: "backgroundAgents", label: "Background Agents" },
  { id: "extraction", label: "Extraction" },
  { id: "transitionPlan", label: "Transition Plan Assessment" },
  { id: "transitionBarrier", label: "Transition Barrier Assessment" },
  { id: "identity", label: "Identity Resolution" },
  { id: "discovery", label: "Document Discovery" },
  { id: "portfolio-monitoring", label: "Portfolio Risk Monitoring Tool" },
  { id: "review", label: "Review Queue" },
  { id: "history", label: "Run History" },
  { id: "engagement", label: "Engagement" },
  { id: "voting", label: "Voting" },
  { id: "reporting", label: "Presentations & Reports" },
  { id: "strategyReplication", label: "Strategy Replication" },
  { id: "decision", label: "Decision Studio" },
  { id: "index", label: "Index Construction" },
  { id: "library", label: "Data Library" },
] as const;

export type TabId = (typeof TABS)[number]["id"];

export const DEFAULT_TAB: TabId = "dashboard";

export function isTabId(value: string | null | undefined): value is TabId {
  return TABS.some((t) => t.id === value);
}

// Purely a sidebar presentation grouping -- ids must match TABS above.
export const NAV_GROUPS: { label: string | null; ids: readonly TabId[] }[] = [
  { label: null, ids: ["dashboard", "search"] },
  { label: "Theme Machine", ids: ["theme", "taxonomy", "emergingThemes"] },
  { label: "Company Research", ids: ["backgroundAgents", "extraction", "identity", "discovery"] },
  {
    label: "Portfolio Analysis",
    ids: ["transitionPlan", "transitionBarrier", "portfolio-monitoring", "strategyReplication", "decision", "index"],
  },
  { label: "StewardIQ", ids: ["engagement", "voting"] },
  { label: "Operations", ids: ["review", "history"] },
  { label: "Output", ids: ["reporting", "library"] },
];

/* --- Sub-tabs. Each page imports its own list; the palette reads them all. */

export const BACKGROUND_AGENT_TABS = [
  { id: "taxonomyResearcher", label: "Taxonomy Researcher" },
  { id: "calibration", label: "Calibration Agent" },
] as const;

export const DATA_LIBRARY_TABS = [
  { id: "results", label: "Run results" },
  { id: "by_company", label: "By company" },
  { id: "parsed", label: "Parsed documents" },
] as const;

export const DECISION_TABS = [
  { id: "data", label: "1 · Data" },
  { id: "profile", label: "2 · Profile" },
  { id: "mechanism", label: "3 · Mechanism" },
  { id: "tree", label: "4 · Decision tree" },
  { id: "results", label: "5 · Results" },
  { id: "movement", label: "6 · Movement" },
  { id: "audit", label: "7 · Audit" },
] as const;

export const INDEX_BUILDER_TABS = [
  { id: "compose", label: "Compose" },
  { id: "calibrations", label: "Calibrations" },
  { id: "result", label: "Result" },
] as const;

export const PORTFOLIO_TABS = [
  { id: "standard", label: "Standard Analytics & Visuals" },
  { id: "pivot", label: "Pivot Explorer" },
  { id: "monitoring", label: "Monitoring & Alerts" },
  { id: "profiles", label: "Company Profiles" },
  { id: "notebook", label: "Custom Analysis" },
  { id: "ask", label: "Ask the Portfolio" },
  { id: "genbi", label: "Generative BI" },
  { id: "governance", label: "Governance & Audit" },
] as const;

export const TAXONOMY_TABS = [
  { id: "library", label: "Library" },
  { id: "new", label: "New taxonomy" },
  { id: "compare", label: "Compare & merge" },
  { id: "universe", label: "Universe builder" },
  { id: "overlap", label: "ETF holdings overlap" },
] as const;

export const SUB_TABS: Partial<Record<TabId, readonly { id: string; label: string }[]>> = {
  backgroundAgents: BACKGROUND_AGENT_TABS,
  library: DATA_LIBRARY_TABS,
  decision: DECISION_TABS,
  index: INDEX_BUILDER_TABS,
  "portfolio-monitoring": PORTFOLIO_TABS,
  taxonomy: TAXONOMY_TABS,
};

export interface Destination {
  tab: TabId;
  sub?: string;
  label: string;
  /** The page a sub-tab belongs to, shown as context in the palette. */
  context?: string;
  group: string | null;
}

/** Every reachable view, flattened for the command palette. */
export const DESTINATIONS: Destination[] = NAV_GROUPS.flatMap((group) =>
  group.ids.flatMap((id) => {
    const tab = TABS.find((t) => t.id === id)!;
    const here: Destination = { tab: id, label: tab.label, group: group.label };
    const subs = (SUB_TABS[id] ?? []).map<Destination>((s) => ({
      tab: id,
      sub: s.id,
      label: s.label,
      context: tab.label,
      group: group.label,
    }));
    return [here, ...subs];
  })
);
