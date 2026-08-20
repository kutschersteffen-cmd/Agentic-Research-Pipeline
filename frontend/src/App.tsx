import { useState } from "react";
import { ThemeBuilder } from "./pages/ThemeBuilder";
import { ExtractionBuilder } from "./pages/ExtractionBuilder";
import { CompanyFinancials } from "./pages/CompanyFinancials";
import { DocumentDiscovery } from "./pages/DocumentDiscovery";
import { IdentityResolution } from "./pages/IdentityResolution";
import { ReviewQueue } from "./pages/ReviewQueue";
import { RunHistory } from "./pages/RunHistory";
import { TaxonomyLibrary } from "./pages/TaxonomyLibrary";
import { MonitoringDashboard } from "./pages/MonitoringDashboard";
import { PortfolioRisk } from "./pages/PortfolioRisk";
import { ClimateAnalytics } from "./pages/ClimateAnalytics";

const TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "theme", label: "Thematic Universe" },
  { id: "taxonomy", label: "Taxonomy Library" },
  { id: "extraction", label: "Data Extraction" },
  { id: "financials", label: "Company Financials" },
  { id: "identity", label: "Identity Resolution" },
  { id: "discovery", label: "Document Discovery" },
  { id: "portfolio", label: "Portfolio Risk" },
  { id: "climate", label: "Climate Analytics" },
  { id: "review", label: "Review Queue" },
  { id: "history", label: "Run History" },
] as const;

function App() {
  const [active, setActive] = useState<(typeof TABS)[number]["id"]>("dashboard");
  const [pendingUniverse, setPendingUniverse] = useState<{ path: string; count: number } | null>(null);
  const [pendingDiscoveryUniverse, setPendingDiscoveryUniverse] = useState<{ path: string; count: number } | null>(null);

  function sendToExtraction(path: string, count: number) {
    setPendingUniverse({ path, count });
    setActive("extraction");
  }

  function sendToDiscovery(path: string, count: number) {
    setPendingDiscoveryUniverse({ path, count });
    setActive("discovery");
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
        {active === "theme" && <ThemeBuilder onSendToExtraction={sendToExtraction} />}
        {active === "taxonomy" && <TaxonomyLibrary />}
        {active === "extraction" && <ExtractionBuilder pendingUniverse={pendingUniverse} />}
        {active === "financials" && <CompanyFinancials pendingUniverse={pendingUniverse} />}
        {active === "identity" && <IdentityResolution onSendToDiscovery={sendToDiscovery} />}
        {active === "discovery" && <DocumentDiscovery pendingUniverse={pendingDiscoveryUniverse} />}
        {active === "portfolio" && <PortfolioRisk />}
        {active === "climate" && <ClimateAnalytics />}
        {active === "review" && <ReviewQueue />}
        {active === "history" && <RunHistory />}
      </main>
    </div>
  );
}

export default App;
