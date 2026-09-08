import { useState } from "react";
import { ThemeMachine } from "./pages/ThemeMachine";
import { StewardIQ } from "./pages/StewardIQ";
import { IdentityDiscovery } from "./pages/IdentityDiscovery";
import { BackgroundAgents } from "./pages/BackgroundAgents";
import { MonitoringDashboard } from "./pages/MonitoringDashboard";
import { PortfolioRiskMonitoringTool } from "./pages/PortfolioRiskMonitoringTool";
import { Runs } from "./pages/Runs";
import { DataLibrary } from "./pages/DataLibrary";

const TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "themeMachine", label: "Theme Machine" },
  { id: "backgroundAgents", label: "Background Agents" },
  { id: "stewardIQ", label: "StewardIQ" },
  { id: "identityDiscovery", label: "Identity & Discovery" },
  { id: "portfolio-monitoring", label: "Portfolio Risk Monitoring Tool" },
  { id: "runs", label: "Runs" },
  { id: "library", label: "Data Library" },
] as const;

type TabId = (typeof TABS)[number]["id"];

// Where a Dashboard run row's type should jump to -- the tool that owns
// that run_type, and (for the multi-tool tabs) which of its sub-tabs.
// proxy_voting has no entry: its dedicated tab was removed and the
// Dashboard's voting summary is read-only.
const RUN_TYPE_NAV: Partial<Record<string, { tab: TabId; sub?: string }>> = {
  theme: { tab: "themeMachine", sub: "thematic" },
  extraction: { tab: "stewardIQ", sub: "extraction" },
  financials: { tab: "stewardIQ", sub: "extraction" },
  transition_plan: { tab: "stewardIQ", sub: "transitionPlan" },
  identity: { tab: "identityDiscovery", sub: "identity" },
  discovery: { tab: "identityDiscovery", sub: "discovery" },
  taxonomy_research: { tab: "backgroundAgents", sub: "taxonomyResearcher" },
  calibration: { tab: "backgroundAgents", sub: "calibration" },
};

function App() {
  const [active, setActive] = useState<TabId>("dashboard");
  const [pendingUniverse, setPendingUniverse] = useState<{ path: string; count: number } | null>(null);
  const [initialSub, setInitialSub] = useState<string | null>(null);

  function sendToExtraction(path: string, count: number) {
    setPendingUniverse({ path, count });
    setInitialSub(null);
    setActive("stewardIQ");
  }

  function goToTab(tab: TabId) {
    setInitialSub(null);
    setActive(tab);
  }

  function openRunType(runType: string) {
    const target = RUN_TYPE_NAV[runType];
    if (!target) return;
    setInitialSub(target.sub ?? null);
    setActive(target.tab);
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Agentic Research Pipeline</h1>
        <p className="tagline">Thematic investment universes, schema-driven document research, and portfolio risk &amp; climate analytics, at scale.</p>
      </header>
      <nav className="app-nav">
        {TABS.map((t) => (
          <button key={t.id} className={t.id === active ? "nav-tab active" : "nav-tab"} onClick={() => goToTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      <main className="app-main">
        {active === "dashboard" && <MonitoringDashboard linkableRunTypes={RUN_TYPE_NAV} onNavigateToRunType={openRunType} />}
        {active === "themeMachine" && <ThemeMachine onSendToExtraction={sendToExtraction} initialSub={initialSub} />}
        {active === "backgroundAgents" && <BackgroundAgents initialSub={initialSub} />}
        {active === "stewardIQ" && <StewardIQ pendingUniverse={pendingUniverse} initialSub={initialSub} />}
        {active === "identityDiscovery" && <IdentityDiscovery initialSub={initialSub} />}
        {active === "portfolio-monitoring" && <PortfolioRiskMonitoringTool />}
        {active === "runs" && <Runs />}
        {active === "library" && <DataLibrary />}
      </main>
    </div>
  );
}

export default App;
