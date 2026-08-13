import { useState } from "react";
import { ThemeBuilder } from "./pages/ThemeBuilder";
import { ExtractionBuilder } from "./pages/ExtractionBuilder";
import { DocumentDiscovery } from "./pages/DocumentDiscovery";
import { ReviewQueue } from "./pages/ReviewQueue";
import { RunHistory } from "./pages/RunHistory";
import { TaxonomyLibrary } from "./pages/TaxonomyLibrary";
import { PortfolioRisk } from "./pages/PortfolioRisk";
import { ClimateAnalytics } from "./pages/ClimateAnalytics";

const TABS = [
  { id: "theme", label: "Thematic Universe" },
  { id: "taxonomy", label: "Taxonomy Library" },
  { id: "extraction", label: "Data Extraction" },
  { id: "discovery", label: "Document Discovery" },
  { id: "portfolio", label: "Portfolio Risk" },
  { id: "climate", label: "Climate Analytics" },
  { id: "review", label: "Review Queue" },
  { id: "history", label: "Run History" },
] as const;

function App() {
  const [active, setActive] = useState<(typeof TABS)[number]["id"]>("theme");
  const [pendingUniverse, setPendingUniverse] = useState<{ path: string; count: number } | null>(null);

  function sendToExtraction(path: string, count: number) {
    setPendingUniverse({ path, count });
    setActive("extraction");
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
        {active === "theme" && <ThemeBuilder onSendToExtraction={sendToExtraction} />}
        {active === "taxonomy" && <TaxonomyLibrary />}
        {active === "extraction" && <ExtractionBuilder pendingUniverse={pendingUniverse} />}
        {active === "discovery" && <DocumentDiscovery />}
        {active === "portfolio" && <PortfolioRisk />}
        {active === "climate" && <ClimateAnalytics />}
        {active === "review" && <ReviewQueue />}
        {active === "history" && <RunHistory />}
      </main>
    </div>
  );
}

export default App;
