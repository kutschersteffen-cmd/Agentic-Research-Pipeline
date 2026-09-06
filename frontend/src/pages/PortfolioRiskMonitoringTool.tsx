import { useState } from "react";
import { PortfolioPaneProvider } from "../context/PortfolioPaneContext";
import { PersistentSelectionPane } from "../components/PersistentSelectionPane";
import { StandardAnalytics } from "./portfolio-monitoring/StandardAnalytics";
import { PivotExplorer } from "./portfolio-monitoring/PivotExplorer";
import { MonitoringAlerts } from "./portfolio-monitoring/MonitoringAlerts";
import { CompanyProfiles } from "./portfolio-monitoring/CompanyProfiles";
import { CustomAnalysisStub } from "./portfolio-monitoring/CustomAnalysisStub";
import { AskThePortfolio } from "./portfolio-monitoring/AskThePortfolio";
import { GovernanceAudit } from "./portfolio-monitoring/GovernanceAudit";

const SUB_TABS = [
  { id: "standard", label: "Standard Analytics & Visuals" },
  { id: "pivot", label: "Pivot Explorer" },
  { id: "monitoring", label: "Monitoring & Alerts" },
  { id: "profiles", label: "Company Profiles" },
  { id: "notebook", label: "Custom Analysis" },
  { id: "ask", label: "Ask the Portfolio" },
  { id: "governance", label: "Governance & Audit" },
] as const;

/** One top-level tool (spec §9): a persistent portfolio/date selection
 * pane that isn't itself a sub-tab, plus one MECE sub-tab per capability
 * area. Sub-tab 1 (Standard Analytics) is explicitly a curated view of
 * sub-tab 2's (Pivot Explorer) engine, not a separate data path -- the
 * one place two sub-tabs share a home section, per the spec. */
export function PortfolioRiskMonitoringTool() {
  return (
    <PortfolioPaneProvider>
      <Inner />
    </PortfolioPaneProvider>
  );
}

function Inner() {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>("standard");

  return (
    <div className="page">
      <h2>Portfolio Risk Monitoring Tool</h2>
      <p className="help-text">
        Select a portfolio (or group) and an as-of date below -- the selection carries across every sub-tab. See{" "}
        <code>docs/PORTFOLIO_RISK_EXPOSURE_PLAN.md</code> for the underlying engine and{" "}
        <code>docs/SPEC_GAP_ANALYSIS.md</code> for how this compares against the functional spec.
      </p>

      <PersistentSelectionPane />

      <nav className="sub-nav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {sub === "standard" && <StandardAnalytics />}
      {sub === "pivot" && <PivotExplorer />}
      {sub === "monitoring" && <MonitoringAlerts />}
      {sub === "profiles" && <CompanyProfiles />}
      {sub === "notebook" && <CustomAnalysisStub />}
      {sub === "ask" && <AskThePortfolio />}
      {sub === "governance" && <GovernanceAudit />}
    </div>
  );
}
