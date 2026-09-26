import { useEffect, useRef, useState } from "react";
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
import type { ReviewableRunKind } from "./types";

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
  { id: "voting", label: "Voting" },
  { id: "reporting", label: "Presentations & Reports" },
  { id: "strategyReplication", label: "Strategy Replication" },
  { id: "decision", label: "Decision Studio" },
  { id: "index", label: "Index Construction" },
  { id: "library", label: "Data Library" },
] as const;

// Purely a sidebar presentation grouping -- ids must match TABS above.
const NAV_GROUPS: { label: string | null; ids: readonly (typeof TABS)[number]["id"][] }[] = [
  { label: null, ids: ["dashboard", "search"] },
  { label: "Theme Machine", ids: ["theme", "taxonomy", "emergingThemes"] },
  { label: "Company Research", ids: ["backgroundAgents", "extraction", "identity", "discovery"] },
  { label: "Portfolio Analysis", ids: ["transitionPlan", "transitionBarrier", "portfolio-monitoring", "strategyReplication", "decision", "index"] },
  { label: "StewardIQ", ids: ["engagement", "voting"] },
  { label: "Operations", ids: ["review", "history"] },
  { label: "Output", ids: ["reporting", "library"] },
];

function App() {
  const [active, setActive] = useState<(typeof TABS)[number]["id"]>("dashboard");
  const [pendingUniverse, setPendingUniverse] = useState<{ path: string; count: number } | null>(null);
  const [pendingDiscoveryUniverse, setPendingDiscoveryUniverse] = useState<{ path: string; count: number } | null>(null);
  const [pendingTaxonomyId, setPendingTaxonomyId] = useState<string | null>(null);
  const [pendingReview, setPendingReview] = useState<{ kind: ReviewableRunKind; runId: string } | null>(null);

  // Below 760px the sidebar is an off-canvas drawer; on desktop navOpen is
  // ignored by the CSS.
  const [navOpen, setNavOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!navOpen) return;
    const menu = menuRef.current;
    navRef.current?.querySelector<HTMLButtonElement>(".nav-tab.active")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setNavOpen(false);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      menu?.focus();
    };
  }, [navOpen]);

  function go(id: (typeof TABS)[number]["id"]) {
    setActive(id);
    setNavOpen(false);
  }

  function sendToExtraction(path: string, count: number) {
    setPendingUniverse({ path, count });
    setActive("extraction");
  }

  function sendToDiscovery(path: string, count: number) {
    setPendingDiscoveryUniverse({ path, count });
    setActive("discovery");
  }

  function sendToTheme(taxonomyId: string) {
    setPendingTaxonomyId(taxonomyId);
    setActive("theme");
  }

  function openReview(kind: ReviewableRunKind, runId: string) {
    setPendingReview({ kind, runId });
    setActive("review");
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
        <nav className="app-nav">
          {NAV_GROUPS.map((group, i) => (
            <div className="nav-group" key={group.label ?? `group-${i}`}>
              {group.label && <div className="nav-group-label">{group.label}</div>}
              {group.ids.map((id) => {
                const t = TABS.find((tab) => tab.id === id)!;
                return (
                  <button
                    key={t.id}
                    className={t.id === active ? "nav-tab active" : "nav-tab"}
                    aria-current={t.id === active ? "page" : undefined}
                    onClick={() => go(t.id)}
                  >
                    <span className="nav-tab-icon">{NAV_ICONS[t.id]}</span>
                    <span className="nav-tab-label">{t.label}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </nav>
      </aside>
      <main className="app-main">
        {active === "dashboard" && <MonitoringDashboard onNavigate={setActive} onOpenReview={openReview} />}
        {active === "search" && <Search />}
        {active === "theme" && <ThemeBuilder onSendToExtraction={sendToExtraction} pendingTaxonomyId={pendingTaxonomyId} />}
        {active === "taxonomy" && <TaxonomyLibrary onUseInTheme={sendToTheme} />}
        {active === "emergingThemes" && <EmergingThemesDetector onNavigate={setActive} />}
        {active === "backgroundAgents" && <BackgroundAgents />}
        {active === "extraction" && <Extraction pendingUniverse={pendingUniverse} />}
        {active === "transitionPlan" && <TransitionPlanAssessment pendingUniverse={pendingUniverse} />}
        {active === "transitionBarrier" && <TransitionBarrierAssessment />}
        {active === "identity" && <IdentityResolution onSendToDiscovery={sendToDiscovery} />}
        {active === "discovery" && <DocumentDiscovery pendingUniverse={pendingDiscoveryUniverse} />}
        {active === "portfolio-monitoring" && <PortfolioRiskMonitoringTool />}
        {active === "review" && <ReviewQueue pendingReview={pendingReview} />}
        {active === "history" && <RunHistory onOpenReview={openReview} />}
        {active === "engagement" && <EngagementDashboard />}
        {active === "voting" && <VotingRuns />}
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
