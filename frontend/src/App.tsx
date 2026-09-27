import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import { ReviewerField } from "./components/ReviewerField";
import { ThemeBuilder } from "./pages/ThemeBuilder";
import { Extraction } from "./pages/Extraction";
import { TransitionPlanAssessment } from "./pages/TransitionPlanAssessment";
import { TransitionBarrierAssessment } from "./pages/TransitionBarrierAssessment";
import { DocumentDiscovery } from "./pages/DocumentDiscovery";
import { EmergingThemesDetector } from "./pages/EmergingThemesDetector";
import { IdentityResolution } from "./pages/IdentityResolution";
import { ReviewQueue } from "./pages/ReviewQueue";
import { RunHistory } from "./pages/RunHistory";
import { DataLibrary } from "./pages/DataLibrary";
import { TaxonomyLibrary } from "./pages/TaxonomyLibrary";
import { BackgroundAgents } from "./pages/BackgroundAgents";
import { MonitoringDashboard } from "./pages/MonitoringDashboard";
import { EngagementDashboard } from "./pages/EngagementDashboard";
import { VotingRuns } from "./pages/VotingRuns";
import { PortfolioRiskMonitoringTool } from "./pages/PortfolioRiskMonitoringTool";
import { ReportBuilder } from "./pages/ReportBuilder";
import { StrategyReplication } from "./pages/StrategyReplication";
import { Search } from "./pages/Search";
import { DecisionStudio } from "./pages/DecisionStudio";
import { IndexBuilder } from "./pages/IndexBuilder";
import { NAV_ICONS } from "./components/NavIcons";
import type { ReviewableRunKind, RunManifest } from "./types";

const TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "search", label: "Search" },
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
  { id: "engagement", label: "Engagement" },
  { id: "voting", label: "Proxy Voting" },
  { id: "reporting", label: "Presentations & Reports" },
  { id: "strategyReplication", label: "Strategy Replication" },
  { id: "decision", label: "Decision Studio" },
  { id: "index", label: "Index Construction" },
  { id: "library", label: "Data Library" },
] as const;

type TabId = (typeof TABS)[number]["id"];

// Purely a sidebar presentation grouping -- ids must match TABS above.
// Ordered by the stewardship team's day: what waits on a person first, then
// their own work, then the research and portfolio tools that feed it.
const NAV_GROUPS: { label: string | null; ids: readonly TabId[] }[] = [
  { label: null, ids: ["dashboard", "search"] },
  { label: "Needs you", ids: ["review", "voting"] },
  { label: "Stewardship", ids: ["engagement", "transitionPlan", "transitionBarrier"] },
  { label: "Research", ids: ["theme", "taxonomy", "emergingThemes", "extraction", "identity", "discovery", "backgroundAgents"] },
  { label: "Portfolio", ids: ["portfolio-monitoring", "strategyReplication", "decision", "index"] },
  { label: "Output", ids: ["reporting", "library", "history"] },
];

const REVIEWABLE = new Set<string>(["theme", "extraction", "financials", "identity"]);

/** The URL is the source of truth for where you are: `#/<tab>/<param>...`,
 * so refresh, Back and a pasted link all land on the same view -- e.g.
 * `#/voting/<run id>` or `#/review/extraction/<run id>`. */
function parseHash(): { tab: TabId; params: string[] } {
  const [tab, ...params] = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  return TABS.some((t) => t.id === tab) ? { tab: tab as TabId, params } : { tab: "dashboard", params: [] };
}

function navigate(tab: TabId, ...params: string[]) {
  window.location.hash = "/" + [tab, ...params].map(encodeURIComponent).join("/");
}

function App() {
  const [route, setRoute] = useState(parseHash);
  const active = route.tab;
  const [waiting, setWaiting] = useState<{ review: number; voting: number } | null>(null);
  const [pendingUniverse, setPendingUniverse] = useState<{ path: string; count: number } | null>(null);
  const [pendingDiscoveryUniverse, setPendingDiscoveryUniverse] = useState<{ path: string; count: number } | null>(null);
  const [pendingTaxonomyId, setPendingTaxonomyId] = useState<string | null>(null);

  useEffect(() => {
    const onHash = () => {
      setRoute(parseHash());
      setNavOpen(false);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Counts on the "Needs you" items, refreshed on every navigation. Failure
  // leaves them off rather than showing a zero nobody measured.
  useEffect(() => {
    api
      .listRuns()
      .then((res) => {
        const runs = (res as { runs: RunManifest[] }).runs;
        const sum = (keep: (r: RunManifest) => boolean) => runs.filter(keep).reduce((n, r) => n + r.review_count, 0);
        setWaiting({ review: sum((r) => REVIEWABLE.has(r.run_type)), voting: sum((r) => r.run_type === "proxy_voting") });
      })
      .catch(() => setWaiting(null));
  }, [route]);

  const pendingReview =
    active === "review" && route.params.length === 2 && REVIEWABLE.has(route.params[0])
      ? { kind: route.params[0] as ReviewableRunKind, runId: route.params[1] }
      : null;

  // Below 760px the sidebar is an off-canvas drawer; on desktop navOpen is
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

  function sendToExtraction(path: string, count: number) {
    setPendingUniverse({ path, count });
    navigate("extraction");
  }

  function sendToDiscovery(path: string, count: number) {
    setPendingDiscoveryUniverse({ path, count });
    navigate("discovery");
  }

  function sendToTheme(taxonomyId: string) {
    setPendingTaxonomyId(taxonomyId);
    navigate("theme");
  }

  function openReview(kind: ReviewableRunKind, runId: string) {
    navigate("review", kind, runId);
  }

  return (
    <div className={navOpen ? "app-shell nav-open" : "app-shell"}>
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
        <span className="app-sidebar-mark">A</span>
        <span className="app-topbar-title">{TABS.find((t) => t.id === active)!.label}</span>
      </header>
      <div className="nav-scrim" onClick={() => setNavOpen(false)} />
      <aside className="app-sidebar" id="app-sidebar" ref={navRef}>
        <div className="app-sidebar-brand">
          <span className="app-sidebar-mark">A</span>
          <span className="app-sidebar-wordmark">ARP</span>
        </div>
        <div className="app-sidebar-reviewer">
          <ReviewerField />
        </div>
        <nav className="app-nav">
          {NAV_GROUPS.map((group, i) => (
            <div className="nav-group" key={group.label ?? `group-${i}`}>
              {group.label && <div className="nav-group-label">{group.label}</div>}
              {group.ids.map((id) => {
                const t = TABS.find((tab) => tab.id === id)!;
                const count = waiting && (id === "review" || id === "voting") ? waiting[id] : 0;
                return (
                  <a
                    key={t.id}
                    href={`#/${t.id}`}
                    className={t.id === active ? "nav-tab active" : "nav-tab"}
                    aria-current={t.id === active ? "page" : undefined}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="nav-tab-icon">{NAV_ICONS[t.id]}</span>
                    <span className="nav-tab-label">{t.label}</span>
                    {count > 0 && (
                      <span className="nav-count" aria-label={`${count} awaiting a decision`}>
                        {count}
                      </span>
                    )}
                  </a>
                );
              })}
            </div>
          ))}
        </nav>
      </aside>
      <main className="app-main">
        {active === "dashboard" && <MonitoringDashboard onNavigate={go} onOpenReview={openReview} />}
        {active === "search" && <Search />}
        {active === "theme" && <ThemeBuilder onSendToExtraction={sendToExtraction} pendingTaxonomyId={pendingTaxonomyId} />}
        {active === "taxonomy" && <TaxonomyLibrary onUseInTheme={sendToTheme} />}
        {active === "emergingThemes" && <EmergingThemesDetector onNavigate={go} />}
        {active === "backgroundAgents" && <BackgroundAgents />}
        {active === "extraction" && <Extraction pendingUniverse={pendingUniverse} />}
        {active === "transitionPlan" && <TransitionPlanAssessment pendingUniverse={pendingUniverse} />}
        {active === "transitionBarrier" && <TransitionBarrierAssessment />}
        {active === "identity" && <IdentityResolution onSendToDiscovery={sendToDiscovery} />}
        {active === "discovery" && <DocumentDiscovery pendingUniverse={pendingDiscoveryUniverse} />}
        {active === "portfolio-monitoring" && <PortfolioRiskMonitoringTool />}
        {active === "review" && <ReviewQueue key={pendingReview ? `${pendingReview.kind}/${pendingReview.runId}` : "review"} pendingReview={pendingReview} />}
        {active === "history" && <RunHistory onOpenReview={openReview} />}
        {active === "engagement" && <EngagementDashboard />}
        {active === "voting" && <VotingRuns selectedRunId={route.params[0] ?? null} onSelectRun={(id) => navigate("voting", id)} />}
        {active === "reporting" && <ReportBuilder />}
        {active === "strategyReplication" && <StrategyReplication />}
        {active === "decision" && <DecisionStudio />}
        {active === "index" && <IndexBuilder />}
        {active === "library" && <DataLibrary />}
      </main>
    </div>
  );
}

export default App;
