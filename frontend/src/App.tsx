import { useCallback, useEffect, useMemo, useState } from "react";
import { ThemeBuilder } from "./pages/ThemeBuilder";
import { Extraction } from "./pages/Extraction";
import { TransitionPlanAssessment } from "./pages/TransitionPlanAssessment";
import { TransitionBarrierAssessment } from "./pages/TransitionBarrierAssessment";
import { DocumentDiscovery } from "./pages/DocumentDiscovery";
import { EmergingThemesDetector } from "./pages/EmergingThemesDetector";
import { IdentityResolution } from "./pages/IdentityResolution";
import { ReviewQueue } from "./pages/ReviewQueue";
import { RunHistory } from "./pages/RunHistory";
import { DataLibrary } from "./pages/DataLibrary";
import { TaxonomyLibrary } from "./pages/TaxonomyLibrary";
import { BackgroundAgents } from "./pages/BackgroundAgents";
import { MonitoringDashboard } from "./pages/MonitoringDashboard";
import { EngagementDashboard } from "./pages/EngagementDashboard";
import { VotingRuns } from "./pages/VotingRuns";
import { PortfolioRiskMonitoringTool } from "./pages/PortfolioRiskMonitoringTool";
import { ReportBuilder } from "./pages/ReportBuilder";
import { StrategyReplication } from "./pages/StrategyReplication";
import { Search } from "./pages/Search";
import { DecisionStudio } from "./pages/DecisionStudio";
import { IndexBuilder } from "./pages/IndexBuilder";
import { CHROME_ICONS, NAV_ICONS } from "./components/NavIcons";
import { CommandPalette } from "./components/CommandPalette";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { DEFAULT_TAB, NAV_GROUPS, TABS, isTabId } from "./nav";
import { href, navigate, useRoute } from "./router";
import { useDensity, useTheme, type ThemeChoice } from "./theme";
import type { ReviewableRunKind } from "./types";

const SIDEBAR_KEY = "arp:sidebar-collapsed";

// A URL is typed, pasted and edited by hand, so nothing read out of one is
// trusted: an unknown review kind is dropped rather than handed to a page
// that would index a lookup table with it.
const REVIEW_KINDS: ReviewableRunKind[] = ["theme", "extraction", "financials", "identity"];

const THEME_ORDER: ThemeChoice[] = ["system", "light", "dark"];
const THEME_LABEL: Record<ThemeChoice, string> = { system: "System theme", light: "Light", dark: "Dark" };

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "true";
  } catch {
    // Private mode or blocked storage: the sidebar just starts expanded.
    return false;
  }
}

function App() {
  const route = useRoute();
  const active = isTabId(route.tab) ? route.tab : DEFAULT_TAB;

  const [paletteOpen, setPaletteOpen] = useState(false);
  const { choice: themeChoice, setTheme } = useTheme();
  const { density, setDensity } = useDensity();
  const nextTheme = THEME_ORDER[(THEME_ORDER.indexOf(themeChoice) + 1) % THEME_ORDER.length];
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Handoffs between pages travel in the URL, so "send this universe to
  // extraction" produces a link the analyst can keep, not hidden state.
  const universe = route.params.get("universe");
  const universeCount = route.params.get("count");
  const taxonomyId = route.params.get("taxonomy");
  const reviewKind = route.params.get("kind");
  const reviewRun = route.params.get("run");

  // Stable identities: several pages re-run a fetch whenever these change.
  const pendingUniverse = useMemo(() => {
    if (!universe) return null;
    const count = Number(universeCount);
    return { path: universe, count: Number.isFinite(count) ? count : 0 };
  }, [universe, universeCount]);
  const pendingReview = useMemo(() => {
    const kind = REVIEW_KINDS.find((k) => k === reviewKind);
    return kind && reviewRun ? { kind, runId: reviewRun } : null;
  }, [reviewKind, reviewRun]);

  const sendToExtraction = useCallback(
    (path: string, count: number) => navigate("extraction", { params: { universe: path, count } }),
    []
  );
  const sendToDiscovery = useCallback(
    (path: string, count: number) => navigate("discovery", { params: { universe: path, count } }),
    []
  );
  const sendToTheme = useCallback((id: string) => navigate("theme", { params: { taxonomy: id } }), []);
  const openReview = useCallback(
    (kind: ReviewableRunKind, runId: string) => navigate("review", { params: { kind, run: runId } }),
    []
  );

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // An address that names no page (a bare "/", or a stale link to something
  // renamed) resolves to the dashboard, and says so in the URL rather than
  // showing one view while the address bar claims another.
  useEffect(() => {
    if (!isTabId(route.tab)) navigate(DEFAULT_TAB, { replace: true });
  }, [route.tab]);

  // A destination has been reached; the drawer has done its job.
  useEffect(() => setDrawerOpen(false), [route.tab, route.sub]);

  // Widening the window (or rotating a tablet) past the drawer breakpoint
  // puts the sidebar back in the layout, so the drawer -- and its scrim --
  // must stand down with it.
  useEffect(() => {
    const wide = window.matchMedia("(min-width: 901px)");
    const sync = () => wide.matches && setDrawerOpen(false);
    sync();
    wide.addEventListener("change", sync);
    return () => wide.removeEventListener("change", sync);
  }, []);

  function toggleCollapsed() {
    setCollapsed((was) => {
      const next = !was;
      try {
        localStorage.setItem(SIDEBAR_KEY, String(next));
      } catch {
        // Preference is a convenience; losing it changes nothing else.
      }
      return next;
    });
  }

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="app-shell" data-sidebar={collapsed ? "rail" : "full"} data-drawer={drawerOpen ? "open" : "closed"}>
        {drawerOpen && <div className="app-scrim" onClick={() => setDrawerOpen(false)} aria-hidden="true" />}
        <aside className="app-sidebar">
          <div className="app-sidebar-brand">
            <span className="app-sidebar-mark">A</span>
            <span className="app-sidebar-wordmark">ARP</span>
            <button
              type="button"
              className="sidebar-toggle"
              onClick={toggleCollapsed}
              aria-label={collapsed ? "Expand the sidebar" : "Collapse the sidebar"}
              aria-pressed={collapsed}
            >
              {collapsed ? CHROME_ICONS.expand : CHROME_ICONS.collapse}
            </button>
          </div>
          <button type="button" className="palette-trigger" onClick={() => setPaletteOpen(true)}>
            {CHROME_ICONS.search}
            <span className="palette-trigger-label">Go to...</span>
            <kbd className="palette-trigger-key">⌘K</kbd>
          </button>
          <nav className="app-nav" aria-label="Primary">
            {NAV_GROUPS.map((group, i) => (
              <div className="nav-group" key={group.label ?? `group-${i}`}>
                {group.label && <div className="nav-group-label">{group.label}</div>}
                {group.ids.map((id) => {
                  const t = TABS.find((tab) => tab.id === id)!;
                  return (
                    <a
                      key={t.id}
                      className={t.id === active ? "nav-tab active" : "nav-tab"}
                      href={href(t.id)}
                      aria-current={t.id === active ? "page" : undefined}
                      title={t.label}
                    >
                      <span className="nav-tab-icon">{NAV_ICONS[t.id]}</span>
                      <span className="nav-tab-label">{t.label}</span>
                    </a>
                  );
                })}
              </div>
            ))}
          </nav>
          <div className="sidebar-footer">
            <button
              type="button"
              className="sidebar-control"
              onClick={() => setTheme(nextTheme)}
              title={`${THEME_LABEL[themeChoice]} — switch to ${THEME_LABEL[nextTheme].toLowerCase()}`}
              aria-label={`Theme: ${THEME_LABEL[themeChoice]}. Switch to ${THEME_LABEL[nextTheme].toLowerCase()}.`}
            >
              {CHROME_ICONS[themeChoice]}
              <span className="sidebar-control-label">{THEME_LABEL[themeChoice]}</span>
            </button>
            <button
              type="button"
              className="sidebar-control"
              onClick={() => setDensity(density === "compact" ? "comfortable" : "compact")}
              aria-pressed={density === "compact"}
              title={density === "compact" ? "Compact rows — switch to comfortable" : "Comfortable rows — switch to compact"}
              aria-label={`Table rows: ${density}. Switch to ${density === "compact" ? "comfortable" : "compact"}.`}
            >
              {CHROME_ICONS.density}
              <span className="sidebar-control-label">{density === "compact" ? "Compact rows" : "Comfortable rows"}</span>
            </button>
          </div>
        </aside>
        <main className="app-main" id="main" tabIndex={-1}>
          <header className="app-topbar">
            <button
              type="button"
              className="topbar-button"
              onClick={() => setDrawerOpen(true)}
              aria-label="Open the navigation"
              aria-expanded={drawerOpen}
            >
              {CHROME_ICONS.menu}
            </button>
            <span className="app-sidebar-wordmark">ARP</span>
            <button
              type="button"
              className="topbar-button topbar-search"
              onClick={() => setPaletteOpen(true)}
              aria-label="Go to a page"
            >
              {CHROME_ICONS.search}
            </button>
          </header>
          <ErrorBoundary resetKey={`${route.tab}/${route.sub ?? ""}`}>
            {active === "dashboard" && <MonitoringDashboard onNavigate={navigate} onOpenReview={openReview} />}
            {active === "search" && <Search />}
            {active === "theme" && (
              <ThemeBuilder key={taxonomyId ?? "theme"} onSendToExtraction={sendToExtraction} pendingTaxonomyId={taxonomyId} />
            )}
            {active === "taxonomy" && <TaxonomyLibrary onUseInTheme={sendToTheme} />}
            {active === "emergingThemes" && <EmergingThemesDetector onNavigate={navigate} />}
            {active === "backgroundAgents" && <BackgroundAgents />}
            {active === "extraction" && <Extraction key={universe ?? "extraction"} pendingUniverse={pendingUniverse} />}
            {active === "transitionPlan" && <TransitionPlanAssessment key={universe ?? "plan"} pendingUniverse={pendingUniverse} />}
            {active === "transitionBarrier" && <TransitionBarrierAssessment />}
            {active === "identity" && <IdentityResolution onSendToDiscovery={sendToDiscovery} />}
            {active === "discovery" && <DocumentDiscovery key={universe ?? "discovery"} pendingUniverse={pendingUniverse} />}
            {active === "portfolio-monitoring" && <PortfolioRiskMonitoringTool />}
            {active === "review" && <ReviewQueue pendingReview={pendingReview} />}
            {active === "history" && <RunHistory onOpenReview={openReview} />}
            {active === "engagement" && <EngagementDashboard />}
            {active === "voting" && <VotingRuns />}
            {active === "reporting" && <ReportBuilder />}
            {active === "strategyReplication" && <StrategyReplication />}
            {active === "decision" && <DecisionStudio />}
            {active === "index" && <IndexBuilder />}
            {active === "library" && <DataLibrary />}
          </ErrorBoundary>
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </>
  );
}

export default App;
