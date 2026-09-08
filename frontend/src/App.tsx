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

function App() {
  const [active, setActive] = useState<(typeof TABS)[number]["id"]>("dashboard");
  const [pendingUniverse, setPendingUniverse] = useState<{ path: string; count: number } | null>(null);

  function sendToExtraction(path: string, count: number) {
    setPendingUniverse({ path, count });
    setActive("stewardIQ");
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Agentic Research Pipeline</h1>
        <p className="tagline">Thematic investment universes, schema-driven document research, and portfolio risk &amp; climate analytics, at scale.</p>
      </header>
      <nav className="app-nav">
        {TABS.map((t) => (
          <button key={t.id} className={t.id === active ? "nav-tab active" : "nav-tab"} onClick={() => setActive(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      <main className="app-main">
        {active === "dashboard" && <MonitoringDashboard />}
        {active === "themeMachine" && <ThemeMachine onSendToExtraction={sendToExtraction} />}
        {active === "backgroundAgents" && <BackgroundAgents />}
        {active === "stewardIQ" && <StewardIQ pendingUniverse={pendingUniverse} />}
        {active === "identityDiscovery" && <IdentityDiscovery />}
        {active === "portfolio-monitoring" && <PortfolioRiskMonitoringTool />}
        {active === "runs" && <Runs />}
        {active === "library" && <DataLibrary />}
      </main>
    </div>
  );
}

export default App;
