import { useState } from "react";
import { ThemeBuilder } from "./pages/ThemeBuilder";
import { ExtractionBuilder } from "./pages/ExtractionBuilder";
import { CompanyFinancials } from "./pages/CompanyFinancials";
import { TransitionPlanAssessment } from "./pages/TransitionPlanAssessment";
import { DocumentDiscovery } from "./pages/DocumentDiscovery";
import { IdentityResolution } from "./pages/IdentityResolution";
import { ReviewQueue, type RunKind } from "./pages/ReviewQueue";
import { RunHistory } from "./pages/RunHistory";
import { TaxonomyLibrary } from "./pages/TaxonomyLibrary";
import { MonitoringDashboard } from "./pages/MonitoringDashboard";
import { EngagementDashboard } from "./pages/EngagementDashboard";
import { VotingRuns } from "./pages/VotingRuns";
import { PortfolioRisk } from "./pages/PortfolioRisk";
import { ClimateAnalytics } from "./pages/ClimateAnalytics";

type TabId =
  | "dashboard"
  | "theme"
  | "taxonomy"
  | "extraction"
  | "financials"
  | "transitionPlan"
  | "identity"
  | "discovery"
  | "portfolio"
  | "climate"
  | "review"
  | "history"
  | "engagement"
  | "voting";

// Grouped for the left-hand nav pane instead of one flat row of 14 tabs --
// each group mirrors a section of the README (research pipelines vs.
// portfolio/climate vs. the operational review/history views vs. the
// stewardship module), so the grouping itself tells a new user what the
// tool is for, not just where to click.
const NAV_GROUPS: { label: string; tabs: { id: TabId; label: string }[] }[] = [
  { label: "Overview", tabs: [{ id: "dashboard", label: "Dashboard" }] },
  {
    label: "Research Pipelines",
    tabs: [
      { id: "theme", label: "Thematic Universe" },
      { id: "taxonomy", label: "Taxonomy Library" },
      { id: "extraction", label: "Data Extraction" },
      { id: "financials", label: "Company Financials" },
      { id: "transitionPlan", label: "Transition Plan Assessment" },
      { id: "identity", label: "Identity Resolution" },
      { id: "discovery", label: "Document Discovery" },
    ],
  },
  {
    label: "Portfolio & Climate",
    tabs: [
      { id: "portfolio", label: "Portfolio Risk" },
      { id: "climate", label: "Climate Analytics" },
    ],
  },
  {
    label: "Review & History",
    tabs: [
      { id: "review", label: "Review Queue" },
      { id: "history", label: "Run History" },
    ],
  },
  {
    label: "Stewardship",
    tabs: [
      { id: "engagement", label: "Engagement" },
      { id: "voting", label: "Voting" },
    ],
  },
];

function App() {
  const [active, setActive] = useState<TabId>("dashboard");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [pendingUniverse, setPendingUniverse] = useState<{ path: string; count: number } | null>(null);
  const [pendingDiscoveryUniverse, setPendingDiscoveryUniverse] = useState<{ path: string; count: number } | null>(null);
  const [pendingReview, setPendingReview] = useState<{ kind: RunKind; runId: string } | null>(null);

  function selectTab(id: TabId) {
    setActive(id);
    setSidebarOpen(false);
  }

  function sendToExtraction(path: string, count: number) {
    setPendingUniverse({ path, count });
    selectTab("extraction");
  }

  function sendToDiscovery(path: string, count: number) {
    setPendingDiscoveryUniverse({ path, count });
    selectTab("discovery");
  }

  function openReview(kind: RunKind, runId: string) {
    setPendingReview({ kind, runId });
    selectTab("review");
  }

  return (
    <div className="app-layout">
      {sidebarOpen && <div className="sidebar-backdrop open" onClick={() => setSidebarOpen(false)} />}
      <aside className={sidebarOpen ? "app-sidebar open" : "app-sidebar"}>
        <div className="sidebar-brand">Agentic Research Pipeline</div>
        <p className="sidebar-tagline">
          Thematic investment universes, schema-driven document research, stewardship engagement &amp; voting, and
          portfolio risk &amp; climate analytics, at scale.
        </p>
        {NAV_GROUPS.map((group) => (
          <div className="sidebar-group" key={group.label}>
            <div className="sidebar-group-label">{group.label}</div>
            {group.tabs.map((t) => (
              <button key={t.id} className={t.id === active ? "sidebar-link active" : "sidebar-link"} onClick={() => selectTab(t.id)}>
                {t.label}
              </button>
            ))}
          </div>
        ))}
      </aside>
      <div className="app-content">
        <button className="sidebar-toggle" onClick={() => setSidebarOpen(true)}>
          &#9776; Menu
        </button>
        <div className="app-content-inner">
          <main className="app-main">
            {active === "dashboard" && <MonitoringDashboard onNavigate={setActive} onOpenReview={openReview} />}
            {active === "theme" && <ThemeBuilder onSendToExtraction={sendToExtraction} />}
            {active === "taxonomy" && <TaxonomyLibrary />}
            {active === "extraction" && <ExtractionBuilder pendingUniverse={pendingUniverse} />}
            {active === "financials" && <CompanyFinancials pendingUniverse={pendingUniverse} />}
            {active === "transitionPlan" && <TransitionPlanAssessment pendingUniverse={pendingUniverse} />}
            {active === "identity" && <IdentityResolution onSendToDiscovery={sendToDiscovery} />}
            {active === "discovery" && <DocumentDiscovery pendingUniverse={pendingDiscoveryUniverse} />}
            {active === "portfolio" && <PortfolioRisk />}
            {active === "climate" && <ClimateAnalytics />}
            {active === "review" && <ReviewQueue pendingReview={pendingReview} />}
            {active === "history" && <RunHistory onOpenReview={openReview} />}
            {active === "engagement" && <EngagementDashboard />}
            {active === "voting" && <VotingRuns />}
          </main>
        </div>
      </div>
    </div>
  );
}

export default App;
