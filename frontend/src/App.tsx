import { useState } from "react";
import { ThemeBuilder } from "./pages/ThemeBuilder";
import { ExtractionBuilder } from "./pages/ExtractionBuilder";
import { DocumentDiscovery } from "./pages/DocumentDiscovery";
import { ReviewQueue } from "./pages/ReviewQueue";
import { RunHistory } from "./pages/RunHistory";

const TABS = [
  { id: "theme", label: "Thematic Universe", render: () => <ThemeBuilder /> },
  { id: "extraction", label: "Data Extraction", render: () => <ExtractionBuilder /> },
  { id: "discovery", label: "Document Discovery", render: () => <DocumentDiscovery /> },
  { id: "review", label: "Review Queue", render: () => <ReviewQueue /> },
  { id: "history", label: "Run History", render: () => <RunHistory /> },
] as const;

function App() {
  const [active, setActive] = useState<(typeof TABS)[number]["id"]>("theme");
  const activeTab = TABS.find((t) => t.id === active)!;

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Agentic Research Pipeline</h1>
        <p className="tagline">Thematic investment universes &amp; schema-driven document research, at scale.</p>
      </header>
      <nav className="app-nav">
        {TABS.map((t) => (
          <button key={t.id} className={t.id === active ? "nav-tab active" : "nav-tab"} onClick={() => setActive(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      <main className="app-main">{activeTab.render()}</main>
    </div>
  );
}

export default App;
