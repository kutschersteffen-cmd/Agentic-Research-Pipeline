import { useState } from "react";
import { PortfolioPaneProvider } from "../context/PortfolioPaneContext";
import { PersistentSelectionPane } from "../components/PersistentSelectionPane";
import { StandardAnalytics } from "./portfolio-monitoring/StandardAnalytics";
import { PivotExplorer } from "./portfolio-monitoring/PivotExplorer";
import { MonitoringAlerts } from "./portfolio-monitoring/MonitoringAlerts";
import { CompanyProfiles } from "./portfolio-monitoring/CompanyProfiles";
import { AskThePortfolio } from "./portfolio-monitoring/AskThePortfolio";
import { GenerativeBI } from "./portfolio-monitoring/GenerativeBI";
import { GovernanceAudit } from "./portfolio-monitoring/GovernanceAudit";

const SUB_TABS = [
  { id: "standard", label: "Standard Analytics & Visuals" },
  { id: "pivot", label: "Pivot Explorer" },
  { id: "monitoring", label: "Monitoring & Alerts" },
  { id: "profiles", label: "Company Profiles" },
  { id: "ask", label: "Ask the Portfolio" },
  { id: "genbi", label: "Generative BI" },
  { id: "governance", label: "Governance & Audit" },
] as const;

/** One top-level tool (spec §9): a persistent portfolio/date selection
 * pane that isn't itself a sub-tab, plus one MECE sub-tab per capability
 * area. Sub-tab 1 (Standard Analytics) is explicitly a curated view of
 * sub-tab 2's (Pivot Explorer) engine, not a separate data path -- the
 * one place two sub-tabs share a home section, per the spec. */
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
  const [sub, setSub] = useState<SubId>(SUB_TABS.some((t) => t.id === initialSub) ? (initialSub as SubId) : "standard");

  return (
    <div className="page">
      <h2>Risk Monitoring</h2>
      <p className="help-text">Pick a portfolio or group and an as-of date; the selection carries across every tab below.</p>

      <PersistentSelectionPane onSendUniverse={onSendUniverse} />

      <nav className="sub-nav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} aria-pressed={t.id === sub} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {sub === "standard" && <StandardAnalytics />}
      {sub === "pivot" && <PivotExplorer />}
      {sub === "monitoring" && <MonitoringAlerts />}
      {sub === "profiles" && <CompanyProfiles />}
      {sub === "ask" && <AskThePortfolio />}
      {sub === "genbi" && <GenerativeBI />}
      {sub === "governance" && <GovernanceAudit />}
    </div>
  );
}
