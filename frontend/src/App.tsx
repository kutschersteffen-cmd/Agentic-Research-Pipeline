import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import { canLeave } from "./lib/leaveGuard";
import { ReviewerField } from "./components/ReviewerField";
import { SignedInAs } from "./components/SignedInAs";
import { ProcessBar, StartPage, WorkspaceOverview, stageDecisions } from "./pages/ProcessHub";
import { WORKSPACES, workspaceOfProcess, type WorkspaceId } from "./lib/processes";
import { STAGE_TABS } from "./pages/steward/common";
import { SUB_TABS as RISK_TABS } from "./lib/subTabs";
import { CommandPalette, type PaletteItem } from "./components/CommandPalette";
import { ThemeSwitch } from "./components/ThemeSwitch";
import { NAV_ICONS } from "./components/NavIcons";
import type { ReviewableRunKind, RunManifest, UniverseHandoff } from "./types";
import { runTypeLabel } from "./lib/runs";

// Pages load on demand so the first screen does not ship every page and its editors.
const ThemeBuilder = lazy(() => import("./pages/ThemeBuilder").then((x) => ({ default: x.ThemeBuilder })));
const Extraction = lazy(() => import("./pages/Extraction").then((x) => ({ default: x.Extraction })));
const TransitionBarrierAssessment = lazy(() => import("./pages/TransitionBarrierAssessment").then((x) => ({ default: x.TransitionBarrierAssessment })));
const DocumentDiscovery = lazy(() => import("./pages/DocumentDiscovery").then((x) => ({ default: x.DocumentDiscovery })));
const EmergingThemesDetector = lazy(() => import("./pages/EmergingThemesDetector").then((x) => ({ default: x.EmergingThemesDetector })));
const IdentityResolution = lazy(() => import("./pages/IdentityResolution").then((x) => ({ default: x.IdentityResolution })));
const ReviewQueue = lazy(() => import("./pages/ReviewQueue").then((x) => ({ default: x.ReviewQueue })));
const RunHistory = lazy(() => import("./pages/RunHistory").then((x) => ({ default: x.RunHistory })));
const DataLibrary = lazy(() => import("./pages/DataLibrary").then((x) => ({ default: x.DataLibrary })));
const TaxonomyLibrary = lazy(() => import("./pages/TaxonomyLibrary").then((x) => ({ default: x.TaxonomyLibrary })));
const BackgroundAgents = lazy(() => import("./pages/BackgroundAgents").then((x) => ({ default: x.BackgroundAgents })));
const MonitoringDashboard = lazy(() => import("./pages/MonitoringDashboard").then((x) => ({ default: x.MonitoringDashboard })));
const EngagementDashboard = lazy(() => import("./pages/EngagementDashboard").then((x) => ({ default: x.EngagementDashboard })));
const VotingRuns = lazy(() => import("./pages/VotingRuns").then((x) => ({ default: x.VotingRuns })));
const StewardWorkflow = lazy(() => import("./pages/StewardWorkflow").then((x) => ({ default: x.StewardWorkflow })));
const PortfolioRiskMonitoringTool = lazy(() => import("./pages/PortfolioRiskMonitoringTool").then((x) => ({ default: x.PortfolioRiskMonitoringTool })));
const ReportBuilder = lazy(() => import("./pages/ReportBuilder").then((x) => ({ default: x.ReportBuilder })));
const StrategyReplication = lazy(() => import("./pages/StrategyReplication").then((x) => ({ default: x.StrategyReplication })));
const Search = lazy(() => import("./pages/Search").then((x) => ({ default: x.Search })));
const SecurityMaster = lazy(() => import("./pages/SecurityMaster").then((x) => ({ default: x.SecurityMaster })));
const Feeds = lazy(() => import("./pages/Feeds").then((x) => ({ default: x.Feeds })));
const Issues = lazy(() => import("./pages/Issues").then((x) => ({ default: x.Issues })));
const SmartSearch = lazy(() => import("./pages/SmartSearch").then((x) => ({ default: x.SmartSearch })));
const Outputs = lazy(() => import("./pages/Outputs").then((x) => ({ default: x.Outputs })));
const Arcade = lazy(() => import("./pages/Arcade").then((x) => ({ default: x.Arcade })));
const Lab = lazy(() => import("./pages/Lab").then((x) => ({ default: x.Lab })));
const DecisionStudio = lazy(() => import("./pages/DecisionStudio").then((x) => ({ default: x.DecisionStudio })));
const IndexBuilder = lazy(() => import("./pages/IndexBuilder").then((x) => ({ default: x.IndexBuilder })));
const ArgusUniverse = lazy(() => import("./pages/ArgusUniverse").then((x) => ({ default: x.ArgusUniverse })));
const XbrlFacts = lazy(() => import("./pages/XbrlFacts").then((x) => ({ default: x.XbrlFacts })));

const TABS = [
  { id: "home", label: "Start" },
  { id: "stewardiq", label: "StewardIQ" },
  { id: "argus", label: "Argus" },
  { id: "argusUniverse", label: "Universe" },
  { id: "transitionIntel", label: "Transition Intelligence Platform" },
  { id: "rdLab", label: "R&D Lab" },
  { id: "dataHub", label: "Data Hub" },
  { id: "dashboard", label: "Dashboard" },
  { id: "search", label: "Search" },
  { id: "securityMaster", label: "Security Master" },
  { id: "feeds", label: "Feeds" },
  { id: "issues", label: "Issues" },
  { id: "smartSearch", label: "Smart Search" },
  { id: "outputs", label: "Outputs" },
  { id: "theme", label: "Thematic Universe" },
  { id: "taxonomy", label: "Taxonomy Library" },
  { id: "emergingThemes", label: "Emerging Themes" },
  { id: "backgroundAgents", label: "Background Agents" },
  { id: "extraction", label: "Extraction" },
  { id: "transitionPlan", label: "Transition Plan" },
  { id: "transitionBarrier", label: "Transition Barriers" },
  { id: "identity", label: "Identity Resolution" },
  { id: "discovery", label: "Document Discovery" },
  { id: "portfolio-monitoring", label: "Risk Monitoring" },
  { id: "review", label: "Review Queue" },
  { id: "history", label: "Run History" },
  { id: "stewardship", label: "Steward Workflow" },
  { id: "engagement", label: "Engagement" },
  { id: "voting", label: "Proxy Voting" },
  { id: "reporting", label: "Presentations & Reports" },
  { id: "strategyReplication", label: "Strategy Replication" },
  { id: "decision", label: "Decision Studio" },
  { id: "index", label: "Index Construction" },
  { id: "xbrl", label: "XBRL Facts" },
  { id: "library", label: "Data Library" },
  { id: "arcade", label: "Arcade" },
  { id: "lab", label: "Lab" },
] as const;

type TabId = (typeof TABS)[number]["id"];

// Screens that share one sidebar item, switched by a tab strip above the page.
// Every id keeps its own route, so deep links and Processes steps still land.
const HUBS: { label: string; tabs: [TabId, string][] }[] = [
  { label: "Library", tabs: [["library", "Data Library"], ["search", "Search"]] },
  { label: "Onboard issuers", tabs: [["identity", "1 Resolve identities"], ["discovery", "2 Find documents"]] },
  { label: "Runs", tabs: [["history", "Run history"], ["backgroundAgents", "Standing agents"]] },
];
const hubOf = (id: TabId) => HUBS.find((h) => h.tabs.some(([t]) => t === id));
// Transition Plan is Extraction preset to its profile (Extraction's own
// profile toggle switches it), so the sidebar shows Extraction for both.
const navIdOf = (id: TabId): TabId => (id === "transitionPlan" ? "extraction" : id);
const isWorkspace = (id: string): id is WorkspaceId => WORKSPACES.some((w) => w.id === id);

// Purely a sidebar presentation grouping -- ids must match TABS above; a hub
// is listed by its first tab. What waits on a person first, then the five
// workspaces (each opens on its processes), then output. Every screen is
// also listed under "All screens", which starts folded and opens itself
// while one of its screens is showing.
const NAV_GROUPS: { label: string | null; ids: readonly TabId[]; collapsed?: boolean }[] = [
  { label: null, ids: ["home", "dashboard"] },
  { label: "Needs you", ids: ["review", "voting"] },
  { label: "Workspaces", ids: ["stewardiq", "argus", "argusUniverse", "transitionIntel", "rdLab", "dataHub"] },
  { label: "Output", ids: ["reporting", "library", "history"] },
  {
    label: "All screens",
    ids: ["feeds", "issues", "smartSearch", "outputs", "securityMaster", "stewardship", "engagement", "extraction", "portfolio-monitoring", "transitionBarrier", "emergingThemes", "taxonomy", "theme", "strategyReplication", "decision", "index", "xbrl", "identity", "lab", "arcade"],
    collapsed: true,
  },
];

// Everything the command palette can jump to: every screen (under its hub's
// name where it has one), plus the Steward stages and Risk Monitoring tabs.
const PALETTE_ITEMS: PaletteItem[] = [
  ...TABS.map((t) => ({ label: t.label, hint: hubOf(t.id)?.label.replace(t.label, "") || undefined, href: `#/${t.id}` })),
  ...STAGE_TABS.map((t) => ({ label: t.label, hint: "Steward Workflow", href: `#/stewardship/${t.id}` })),
  ...RISK_TABS.map((t) => ({ label: t.label, hint: "Risk Monitoring", href: `#/portfolio-monitoring/${t.id}` })),
];

const REVIEWABLE = new Set<string>(["theme", "extraction", "financials", "identity"]);

/** A run in the palette opens where its decisions are made, else in Run History. */
const runItem = (r: RunManifest): PaletteItem => ({
  label: `${runTypeLabel(r.run_type)} ${r.run_id}`,
  hint: "Run",
  href: r.run_type === "proxy_voting" ? `#/voting/${r.run_id}` : REVIEWABLE.has(r.run_type) ? `#/review/${r.run_type}/${r.run_id}` : "#/history",
});

/** The URL is the source of truth for where you are: `#/<tab>/<param>...`,
 * so refresh, Back and a pasted link all land on the same view -- e.g.
 * `#/voting/<run id>` or `#/review/extraction/<run id>`. */
function parseHash(hash = window.location.hash): { tab: TabId; params: string[] } {
  const [tab, ...params] = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  // Old links: the Theme Machine and Design Studio boxes merged into R&D Lab;
  // the Processes screen's processes now live on their workspace pages.
  if (tab === "themeMachine" || tab === "designStudio") return { tab: "rdLab", params: [] };
  if (tab === "processes") return { tab: workspaceOfProcess(params[0])?.id ?? "home", params: [] };
  return TABS.some((t) => t.id === tab) ? { tab: tab as TabId, params } : { tab: "home", params: [] };
}

function navigate(tab: TabId, ...params: string[]) {
  window.location.hash = "/" + [tab, ...params].map(encodeURIComponent).join("/");
}

/** ARP mark: a pixel "A"; the apex square is the signal, where a person ratifies. */
function ArpMark() {
  return (
    <svg className="app-sidebar-mark" viewBox="0 0 62 62" aria-hidden="true">
      <path fill="currentColor" d="M14 2h10v10H14zM38 2h10v10H38zM2 14h10v10H2zM50 14h10v10H50zM2 26h10v10H2zM14 26h10v10H14zM26 26h10v10H26zM38 26h10v10H38zM50 26h10v10H50zM2 38h10v10H2zM50 38h10v10H50zM2 50h10v10H2zM50 50h10v10H50z" />
      <rect x="26" y="2" width="10" height="10" fill="var(--hi)" />
    </svg>
  );
}

function App() {
  const [route, setRoute] = useState(parseHash);
  const active = route.tab;
  const [waiting, setWaiting] = useState<{ review: number; voting: number } | null>(null);
  const [openDecisions, setOpenDecisions] = useState(0);
  const [recentRuns, setRecentRuns] = useState<RunManifest[]>([]);
  // One universe in flight between screens, addressed to one of them.
  const [handoff, setHandoff] = useState<(UniverseHandoff & { to: TabId }) | null>(null);
  const pendingFor = (to: TabId) => (handoff?.to === to ? handoff : null);
  const [pendingTaxonomyId, setPendingTaxonomyId] = useState<string | null>(null);

  // The hash last shown, so a navigation the open screen refuses can be put back.
  const shownHash = useRef(window.location.hash);
  useEffect(() => {
    const onHash = () => {
      const next = parseHash();
      if (next.tab !== parseHash(shownHash.current).tab && !canLeave()) {
        // hashchange cannot be cancelled; replaceState restores the URL without firing it again.
        history.replaceState(null, "", shownHash.current || "#");
        return;
      }
      shownHash.current = window.location.hash;
      setRoute(next);
      setNavOpen(false);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // A decision anywhere (see lib/announce) refreshes the counts below.
  const [decidedAt, setDecidedAt] = useState(0);
  useEffect(() => {
    const onDecided = () => setDecidedAt(Date.now());
    window.addEventListener("arp:decided", onDecided);
    return () => window.removeEventListener("arp:decided", onDecided);
  }, []);

  // Counts on the "Needs you" items, refreshed on every navigation and after
  // every decision. Failure leaves them off rather than showing a zero nobody measured.
  useEffect(() => {
    api
      .listRuns()
      .then((res) => {
        const runs = (res as { runs: RunManifest[] }).runs;
        const sum = (keep: (r: RunManifest) => boolean) => runs.filter(keep).reduce((n, r) => n + r.review_count, 0);
        setWaiting({ review: sum((r) => REVIEWABLE.has(r.run_type)), voting: sum((r) => r.run_type === "proxy_voting") });
        setRecentRuns([...runs].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)).slice(0, 50));
      })
      .catch(() => setWaiting(null));
    api.getStewardshipFlow("house").then(
      (flow) => setOpenDecisions(stageDecisions(flow)),
      () => setOpenDecisions(0),
    );
  }, [route, decidedAt]);

  const hub = hubOf(active);
  // The tab title names the screen, for browser tabs and screen readers.
  useEffect(() => {
    document.title = `${hub?.label ?? TABS.find((t) => t.id === active)!.label} · ARP`;
  }, [active, hub]);

  const pendingReview =
    active === "review" && route.params.length === 2 && REVIEWABLE.has(route.params[0])
      ? { kind: route.params[0] as ReviewableRunKind, runId: route.params[1] }
      : null;

  const [paletteOpen, setPaletteOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Below 1024px the sidebar is an off-canvas drawer; on desktop navOpen is
  // ignored by the CSS.
  const [navOpen, setNavOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!navOpen) return;
    const menu = menuRef.current;
    navRef.current?.querySelector<HTMLElement>(".nav-tab.active")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setNavOpen(false);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      menu?.focus();
    };
  }, [navOpen]);

  function go(id: TabId) {
    navigate(id);
    setNavOpen(false);
  }

  const sendUniverse = (from: string) => (to: "extraction" | "transitionPlan" | "discovery" | "xbrl", path: string, count: number) => {
    setHandoff({ path, count, from, to });
    navigate(to);
  };

  function sendToTheme(taxonomyId: string) {
    setPendingTaxonomyId(taxonomyId);
    navigate("theme");
  }

  function openReview(kind: ReviewableRunKind, runId: string) {
    navigate("review", kind, runId);
  }

  return (
    <div className={navOpen ? "app-shell nav-open" : "app-shell"}>
      {/* Routing lives in the hash, so the skip link focuses <main> instead of
          following an in-page anchor. */}
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      <div id="announcer" className="visually-hidden" role="status" aria-live="polite" />
      <header className="app-topbar">
        <button
          ref={menuRef}
          className="app-topbar-menu"
          aria-label="Open navigation"
          aria-expanded={navOpen}
          aria-controls="app-sidebar"
          onClick={() => setNavOpen(true)}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round">
            <path d="M4 7h16M4 12h16M4 17h16" />
          </svg>
        </button>
        <ArpMark />
        <span className="app-topbar-title">{TABS.find((t) => t.id === active)!.label}</span>
      </header>
      <div className="nav-scrim" onClick={() => setNavOpen(false)} />
      <aside className="app-sidebar" id="app-sidebar" ref={navRef}>
        <div className="app-sidebar-brand">
          <ArpMark />
          <span className="app-sidebar-wordmark">ARP</span>
        </div>
        <div className="app-sidebar-reviewer">
          <ReviewerField />
          <SignedInAs />
        </div>
        <button className="palette-trigger" onClick={() => setPaletteOpen(true)}>
          Jump to…
          <kbd>{/Mac|iPhone|iPad/.test(navigator.userAgent) ? "⌘K" : "Ctrl K"}</kbd>
        </button>
        <ThemeSwitch />
        <nav className="app-nav">
          {NAV_GROUPS.map((group, i) => {
            const links = group.ids.map((id) => {
              const t = TABS.find((tab) => tab.id === id)!;
              const h = hubOf(id);
              const current = h ? h.tabs.some(([tid]) => tid === active) : id === navIdOf(active);
              const count = id === "stewardship" ? openDecisions : waiting && (id === "review" || id === "voting") ? waiting[id] : 0;
              return (
                <a
                  key={t.id}
                  href={`#/${t.id}`}
                  className={current ? "nav-tab active" : "nav-tab"}
                  aria-current={current ? "page" : undefined}
                  onClick={() => setNavOpen(false)}
                >
                  <span className="nav-tab-icon">{NAV_ICONS[t.id]}</span>
                  <span className="nav-tab-label">{h?.label ?? t.label}</span>
                  {count > 0 && (
                    <span className="nav-count" aria-label={`${count} ${count === 1 ? "decision" : "decisions"} waiting on you`}>
                      {count}
                    </span>
                  )}
                </a>
              );
            });
            if (group.collapsed) {
              return (
                <details className="nav-more" key={group.label} open={group.ids.includes(navIdOf(active)) || undefined}>
                  <summary className="nav-group-label">{group.label}</summary>
                  <div className="nav-group">{links}</div>
                </details>
              );
            }
            return (
              <div className="nav-group" key={group.label ?? `group-${i}`}>
                {group.label && <div className="nav-group-label">{group.label}</div>}
                {links}
              </div>
            );
          })}
        </nav>
      </aside>
      {paletteOpen && <CommandPalette items={[...PALETTE_ITEMS, ...recentRuns.map(runItem)]} onClose={() => setPaletteOpen(false)} />}
      <main className="app-main" id="main" tabIndex={-1}>
        <ProcessBar tab={active} sub={route.params[0]} />
        {hub && (
          <nav className="sub-nav hub-nav" aria-label={hub.label}>
            {hub.tabs.map(([id, label]) => (
              <a key={id} href={`#/${id}`} className={id === active ? "nav-tab active" : "nav-tab"} aria-current={id === active ? "page" : undefined}>
                {label}
              </a>
            ))}
          </nav>
        )}
        <Suspense fallback={<p className="muted" role="status">Loading…</p>}>
        {active === "home" && <StartPage />}
        {isWorkspace(active) && <WorkspaceOverview key={active} id={active} />}
        {active === "dashboard" && <MonitoringDashboard onNavigate={go} onOpenReview={openReview} />}
        {active === "search" && <Search />}
        {active === "securityMaster" && <SecurityMaster />}
        {active === "feeds" && <Feeds />}
        {active === "issues" && <Issues />}
        {active === "smartSearch" && <SmartSearch />}
        {active === "outputs" && <Outputs />}
        {active === "lab" && <Lab selected={route.params[0] ?? null} />}
        {active === "arcade" && <Arcade selected={route.params[0] ?? null} />}
        {active === "theme" && <ThemeBuilder onSendToExtraction={(path, count) => sendUniverse("Thematic Universe")("extraction", path, count)} pendingTaxonomyId={pendingTaxonomyId} />}
        {active === "taxonomy" && <TaxonomyLibrary onUseInTheme={sendToTheme} />}
        {active === "emergingThemes" && <EmergingThemesDetector onNavigate={go} />}
        {active === "backgroundAgents" && <BackgroundAgents />}
        {active === "extraction" && <Extraction key="extraction" initialTab={route.params[0]} initialAuto={route.params[1] === "auto"} pendingUniverse={pendingFor("extraction")} />}
        {active === "transitionPlan" && <Extraction key="transitionPlan" initialProfile="transition_plan" pendingUniverse={pendingFor("transitionPlan")} />}
        {active === "transitionBarrier" && <TransitionBarrierAssessment />}
        {active === "identity" && <IdentityResolution onSendToDiscovery={(path, count) => sendUniverse("Identity Resolution")("discovery", path, count)} />}
        {active === "discovery" && <DocumentDiscovery pendingUniverse={pendingFor("discovery")} onSendUniverse={sendUniverse("Document Discovery")} />}
        {active === "portfolio-monitoring" && <PortfolioRiskMonitoringTool key={route.params[0]} initialSub={route.params[0]} onSendUniverse={sendUniverse("Risk Monitoring")} />}
        {active === "review" && <ReviewQueue key={pendingReview ? `${pendingReview.kind}/${pendingReview.runId}` : "review"} pendingReview={pendingReview} />}
        {active === "history" && <RunHistory onOpenReview={openReview} />}
        {active === "stewardship" && <StewardWorkflow initialTab={route.params[0]} />}
        {active === "engagement" && <EngagementDashboard />}
        {active === "voting" && <VotingRuns selectedRunId={route.params[0] ?? null} onSelectRun={(id) => navigate("voting", id)} />}
        {active === "reporting" && <ReportBuilder />}
        {active === "strategyReplication" && <StrategyReplication />}
        {active === "decision" && <DecisionStudio key={route.params.join("/")} initialSource={route.params[0]} initialRunId={route.params[1]} />}
        {active === "index" && <IndexBuilder />}
        {active === "argusUniverse" && <ArgusUniverse onSendUniverse={sendUniverse("Argus Universe")} />}
        {active === "xbrl" && <XbrlFacts selectedRunId={route.params[0] ?? null} onSelectRun={(id) => navigate("xbrl", id)} />}
        {active === "library" && <DataLibrary />}
        </Suspense>
      </main>
    </div>
  );
}

export default App;
