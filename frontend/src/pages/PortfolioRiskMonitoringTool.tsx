import { useState } from "react";
import { PortfolioPaneProvider } from "../context/PortfolioPaneContext";
import { PersistentSelectionPane } from "../components/PersistentSelectionPane";
import { StandardAnalytics } from "./portfolio-monitoring/StandardAnalytics";
import { MonitoringAlerts } from "./portfolio-monitoring/MonitoringAlerts";
import { CompanyProfiles } from "./portfolio-monitoring/CompanyProfiles";
import { AskThePortfolio } from "./portfolio-monitoring/AskThePortfolio";
import { SupersetBI } from "./portfolio-monitoring/SupersetBI";
import { HoldingsIntake } from "./portfolio-monitoring/HoldingsIntake";
import { resolveSubTab, SUB_TABS } from "../lib/subTabs";

/** One top-level tool (spec §9): a persistent portfolio/date selection
 * pane that isn't itself a sub-tab, plus one MECE sub-tab per capability
 * area. Ad-hoc slicing lives in Superset (the Dashboards tab), whose
 * native filter bar is that tab's selection UI; old pivot/superset links
 * land there (lib/subTabs). */
type SendUniverse = (to: "transitionPlan" | "extraction" | "discovery", path: string, count: number) => void;

export function PortfolioRiskMonitoringTool({ initialSub, onSendUniverse }: { initialSub?: string; onSendUniverse?: SendUniverse }) {
  return (
    <PortfolioPaneProvider>
      <Inner initialSub={initialSub} onSendUniverse={onSendUniverse} />
    </PortfolioPaneProvider>
  );
}

type SubId = (typeof SUB_TABS)[number]["id"];

function Inner({ initialSub, onSendUniverse }: { initialSub?: string; onSendUniverse?: SendUniverse }) {
  const [sub, setSub] = useState<SubId>(() => resolveSubTab(initialSub, SUB_TABS));

  return (
    <div className="page">
      <h1>Risk Monitoring</h1>
      {/* spec §5: on the Dashboards tab Superset's filter bar is the selection UI */}
      {sub !== "dashboards" && (
        <>
          <p className="help-text">
            Pick a portfolio or group and an as-of date; the selection carries across the tabs below (Dashboards uses
            Superset&apos;s own filter bar).
          </p>
          <PersistentSelectionPane onSendUniverse={onSendUniverse} />
        </>
      )}

      <nav className="sub-nav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} aria-pressed={t.id === sub} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {sub === "standard" && <StandardAnalytics />}
      {sub === "monitoring" && <MonitoringAlerts />}
      {sub === "profiles" && <CompanyProfiles />}
      {sub === "ask" && <AskThePortfolio />}
      {sub === "dashboards" && <SupersetBI />}
      {sub === "holdings" && <HoldingsIntake />}
    </div>
  );
}
