import { useState } from "react";
import { ThemeBuilder } from "./pages/ThemeBuilder";
import { Extraction } from "./pages/Extraction";
import { TransitionPlanAssessment } from "./pages/TransitionPlanAssessment";
import { DocumentDiscovery } from "./pages/DocumentDiscovery";
import { IdentityResolution } from "./pages/IdentityResolution";
import { ReviewQueue } from "./pages/ReviewQueue";
import { RunHistory } from "./pages/RunHistory";
import { TaxonomyLibrary } from "./pages/TaxonomyLibrary";
import { BackgroundAgents } from "./pages/BackgroundAgents";
import { MonitoringDashboard } from "./pages/MonitoringDashboard";
import { EngagementDashboard } from "./pages/EngagementDashboard";
import { VotingRuns } from "./pages/VotingRuns";
import { PortfolioRisk } from "./pages/PortfolioRisk";
import { ClimateAnalytics } from "./pages/ClimateAnalytics";
import type { ReviewableRunKind } from "./types";

const TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "theme", label: "Thematic Universe" },
  { id: "taxonomy", label: "Taxonomy Library" },
  { id: "backgroundAgents", label: "Background Agents" },
  { id: "extraction", label: "Extraction" },
  { id: "transitionPlan", label: "Transition Plan Assessment" },
  { id: "identity", label: "Identity Resolution" },
  { id: "discovery", label: "Document Discovery" },
  { id: "portfolio", label: "Portfolio Risk" },
  { id: "climate", label: "Climate Analytics" },
  { id: "review", label: "Review Queue" },
  { id: "history", label: "Run History" },
  { id: "engagement", label: "Engagement" },
  { id: "voting", label: "Voting" },
] as const;

function App() {
  const [active, setActive] = useState<(typeof TABS)[number]["id"]>("dashboard");
  const [pendingUniverse, setPendingUniverse] = useState<{ path: string; count: number } | null>(null);
  const [pendingDiscoveryUniverse, setPendingDiscoveryUniverse] = useState<{ path: string; count: number } | null>(null);
  const [pendingTaxonomyId, setPendingTaxonomyId] = useState<string | null>(null);
  const [pendingReview, setPendingReview] = useState<{ kind: ReviewableRunKind; runId: string } | null>(null);

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
    <div className="app-shell">
      <header className="app-header">
        <h1>Agentic Research Pipeline</h1>
        <p className="tagline">Thematic investment universes, schema-driven document research, stewardship engagement &amp; voting, and portfolio risk &amp; climate analytics, at scale.</p>
      </header>
      <nav className="app-nav">
        {TABS.map((t) => (
          <button key={t.id} className={t.id === active ? "nav-tab active" : "nav-tab"} onClick={() => setActive(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      <main className="app-main">
        {active === "dashboard" && <MonitoringDashboard onNavigate={setActive} />}
        {active === "theme" && <ThemeBuilder onSendToExtraction={sendToExtraction} pendingTaxonomyId={pendingTaxonomyId} />}
        {active === "taxonomy" && <TaxonomyLibrary onUseInTheme={sendToTheme} />}
        {active === "backgroundAgents" && <BackgroundAgents />}
        {active === "extraction" && <Extraction pendingUniverse={pendingUniverse} />}
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
  );
}

export default App;
