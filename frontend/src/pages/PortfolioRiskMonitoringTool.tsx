import { PortfolioPaneProvider } from "../context/PortfolioPaneContext";
import { PersistentSelectionPane } from "../components/PersistentSelectionPane";
import { StandardAnalytics } from "./portfolio-monitoring/StandardAnalytics";
import { PivotExplorer } from "./portfolio-monitoring/PivotExplorer";
import { MonitoringAlerts } from "./portfolio-monitoring/MonitoringAlerts";
import { CompanyProfiles } from "./portfolio-monitoring/CompanyProfiles";
import { CustomAnalysisStub } from "./portfolio-monitoring/CustomAnalysisStub";
import { AskThePortfolio } from "./portfolio-monitoring/AskThePortfolio";
import { GenerativeBI } from "./portfolio-monitoring/GenerativeBI";
import { GovernanceAudit } from "./portfolio-monitoring/GovernanceAudit";
import { PORTFOLIO_TABS as SUB_TABS } from "../nav";
import { useSubTab } from "../router";
import { PageHeader, TabPanel, Tabs } from "../ui";

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
  const [sub, setSub] = useSubTab(SUB_TABS, "standard");

  return (
    <div className="page">
      <PageHeader
        title="Portfolio Risk Monitoring Tool"
        description={
          <>
            Select a portfolio (or group) and an as-of date below -- the selection carries across every sub-tab. See{" "}
            <code>docs/PORTFOLIO_RISK_EXPOSURE_PLAN.md</code> for the underlying engine and{" "}
            <code>docs/SPEC_GAP_ANALYSIS.md</code> for how this compares against the functional spec.
          </>
        }
      />

      <PersistentSelectionPane />

      <Tabs
        id="portfolio"
        tabs={SUB_TABS}
        active={sub}
        onChange={(id) => setSub(id as typeof sub)}
        label="Portfolio tool"
      />
      <TabPanel id="portfolio" active={sub}>
        {sub === "standard" && <StandardAnalytics />}
        {sub === "pivot" && <PivotExplorer />}
        {sub === "monitoring" && <MonitoringAlerts />}
        {sub === "profiles" && <CompanyProfiles />}
        {sub === "notebook" && <CustomAnalysisStub />}
        {sub === "ask" && <AskThePortfolio />}
        {sub === "genbi" && <GenerativeBI />}
        {sub === "governance" && <GovernanceAudit />}
      </TabPanel>
    </div>
  );
}
