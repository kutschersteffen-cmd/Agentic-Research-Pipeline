import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import { canLeave } from "./lib/leaveGuard";
import { SignedInAs } from "./components/SignedInAs";
import { ThemeBuilder } from "./pages/ThemeBuilder";
import { Extraction } from "./pages/Extraction";
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
import { ProcessOverview, StartPage, stageDecisions } from "./pages/ProcessHub";
import { EngagementDashboard } from "./pages/EngagementDashboard";
import { VotingRuns } from "./pages/VotingRuns";
import { STAGE_TABS, StewardWorkflow } from "./pages/StewardWorkflow";
import { PortfolioRiskMonitoringTool, SUB_TABS as RISK_TABS } from "./pages/PortfolioRiskMonitoringTool";
import { CommandPalette, type PaletteItem } from "./components/CommandPalette";
import { ThemeSwitch } from "./components/ThemeSwitch";
import { ReportBuilder } from "./pages/ReportBuilder";
import { StrategyReplication } from "./pages/StrategyReplication";
import { Search } from "./pages/Search";
import { Arcade } from "./pages/Arcade";
import { DecisionStudio } from "./pages/DecisionStudio";
import { IndexBuilder } from "./pages/IndexBuilder";
import { ProcessBar, Processes } from "./pages/Processes";
import { NAV_ICONS } from "./components/NavIcons";
import type { ReviewableRunKind, RunManifest, UniverseHandoff } from "./types";
import { runTypeLabel } from "./lib/runs";

const TABS = [
  { id: "home", label: "Start" },
  { id: "stewardiq", label: "StewardIQ" },
  { id: "themeMachine", label: "Theme Machine" },
  { id: "designStudio", label: "Design Studio" },
  { id: "dashboard", label: "Dashboard" },
  { id: "processes", label: "Processes" },
  { id: "search", label: "Search" },
  { id: "theme", label: "Thematic Universe" },
  { id: "taxonomy", label: "Taxonomy Library" },
  { id: "emergingThemes", label: "Emerging Themes" },
  { id: "backgroundAgents", label: "Background Agents" },
  { id: "extraction", label: "Extraction" },
  { id: "transitionPlan", label: "Transition Plan" },
  { id: "transitionBarrier", label: "Transition Barriers" },
  { id: "identity", label: "Identity Resolution" },
  { id: "discovery", label: "Document Discovery" },
  { id: "portfolio-monitoring", label: "Risk Monitoring" },
  { id: "review", label: "Review Queue" },
  { id: "history", label: "Run History" },
  { id: "stewardship", label: "Steward Workflow" },
  { id: "engagement", label: "Engagement" },
  { id: "voting", label: "Proxy Voting" },
  { id: "reporting", label: "Presentations & Reports" },
  { id: "strategyReplication", label: "Strategy Replication" },
  { id: "decision", label: "Decision Studio" },
  { id: "index", label: "Index Construction" },
  { id: "library", label: "Data Library" },
  { id: "arcade", label: "Arcade" },
] as const;

type TabId = (typeof TABS)[number]["id"];

// Screens that share one sidebar item, switched by a tab strip above the page.
// Every id keeps its own route, so deep links and Processes steps still land.
const HUBS: { label: string; tabs: [TabId, string][] }[] = [
  { label: "Dashboard", tabs: [["dashboard", "Overview"], ["processes", "Processes"]] },
  { label: "Library", tabs: [["library", "Data Library"], ["search", "Search"]] },
  { label: "Onboard issuers", tabs: [["identity", "1 Resolve identities"], ["discovery", "2 Find documents"]] },
  { label: "Runs", tabs: [["history", "Run history"], ["backgroundAgents", "Standing agents"]] },
];
const hubOf = (id: TabId) => HUBS.find((h) => h.tabs.some(([t]) => t === id));
// Transition Plan is Extraction preset to its profile (Extraction's own
// profile toggle switches it), so the sidebar shows Extraction for both.
// The process overview pages are reached from the start page's boxes, so the
// sidebar shows Start for them.
const navIdOf = (id: TabId): TabId =>
  id === "transitionPlan" ? "extraction" : id === "stewardiq" || id === "themeMachine" || id === "designStudio" ? "home" : id;

// Purely a sidebar presentation grouping -- ids must match TABS above; a hub
// is listed by its first tab. Ordered by the stewardship team's day: what
// waits on a person first, then their own work, then the research and
// portfolio tools that feed it.
// A `collapsed` group starts folded (and opens itself while one of its
// screens is showing): the specialist tools the day-to-day work doesn't need.
const NAV_GROUPS: { label: string | null; ids: readonly TabId[]; collapsed?: boolean }[] = [
  { label: null, ids: ["home", "dashboard", "library"] },
  { label: "Needs you", ids: ["review", "voting"] },
  { label: "Stewardship", ids: ["stewardship", "engagement", "extraction", "transitionBarrier"] },
  { label: "Research", ids: ["theme", "identity"] },
  { label: "Portfolio", ids: ["portfolio-monitoring"] },
  { label: "Output", ids: ["reporting", "history"] },
  { label: "More tools", ids: ["decision", "taxonomy", "emergingThemes", "strategyReplication", "index", "arcade"], collapsed: true },
];

// Everything the command palette can jump to: every screen (under its hub's
// name where it has one), plus the Steward stages and Risk Monitoring tabs.
const PALETTE_ITEMS: PaletteItem[] = [
  ...TABS.map((t) => ({ label: t.label, hint: hubOf(t.id)?.label.replace(t.label, "") || undefined, href: `#/${t.id}` })),
  ...STAGE_TABS.map((t) => ({ label: t.label, hint: "Steward Workflow", href: `#/stewardship/${t.id}` })),
  ...RISK_TABS.map((t) => ({ label: t.label, hint: "Risk Monitoring", href: `#/portfolio-monitoring/${t.id}` })),
];

const REVIEWABLE = new Set<string>(["theme", "extraction", "financials", "identity"]);

/** A run in the palette opens where its decisions are made, else in Run History. */
const runItem = (r: RunManifest): PaletteItem => ({
  label: `${runTypeLabel(r.run_type)} ${r.run_id}`,
  hint: "Run",
  href: r.run_type === "proxy_voting" ? `#/voting/${r.run_id}` : REVIEWABLE.has(r.run_type) ? `#/review/${r.run_type}/${r.run_id}` : "#/history",
});

/** The URL is the source of truth for where you are: `#/<tab>/<param>...`,
 * so refresh, Back and a pasted link all land on the same view -- e.g.
 * `#/voting/<run id>` or `#/review/extraction/<run id>`. */
function parseHash(hash = window.location.hash): { tab: TabId; params: string[] } {
  const [tab, ...params] = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  return TABS.some((t) => t.id === tab) ? { tab: tab as TabId, params } : { tab: "home", params: [] };
}

function navigate(tab: TabId, ...params: string[]) {
  window.location.hash = "/" + [tab, ...params].map(encodeURIComponent).join("/");
}

function App() {
  const [route, setRoute] = useState(parseHash);
  const active = route.tab;
  const [waiting, setWaiting] = useState<{ review: number; voting: number } | null>(null);
  const [openDecisions, setOpenDecisions] = useState(0);
  const [recentRuns, setRecentRuns] = useState<RunManifest[]>([]);
  // One universe in flight between screens, addressed to one of them.
  const [handoff, setHandoff] = useState<(UniverseHandoff & { to: TabId }) | null>(null);
  const pendingFor = (to: TabId) => (handoff?.to === to ? handoff : null);
  const [pendingTaxonomyId, setPendingTaxonomyId] = useState<string | null>(null);

  // The hash last shown, so a navigation the open screen refuses can be put back.
  const shownHash = useRef(window.location.hash);
  useEffect(() => {
    const onHash = () => {
      const next = parseHash();
      if (next.tab !== parseHash(shownHash.current).tab && !canLeave()) {
        // hashchange cannot be cancelled; replaceState restores the URL without firing it again.
        history.replaceState(null, "", shownHash.current || "#");
        return;
      }
      shownHash.current = window.location.hash;
      setRoute(next);
      setNavOpen(false);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // A decision anywhere (see lib/announce) refreshes the counts below.
  const [decidedAt, setDecidedAt] = useState(0);
  useEffect(() => {
    const onDecided = () => setDecidedAt(Date.now());
    window.addEventListener("arp:decided", onDecided);
    return () => window.removeEventListener("arp:decided", onDecided);
  }, []);

  // Counts on the "Needs you" items, refreshed on every navigation and after
  // every decision. Failure leaves them off rather than showing a zero nobody measured.
  useEffect(() => {
    api
      .listRuns()
      .then((res) => {
        const runs = (res as { runs: RunManifest[] }).runs;
        const sum = (keep: (r: RunManifest) => boolean) => runs.filter(keep).reduce((n, r) => n + r.review_count, 0);
        setWaiting({ review: sum((r) => REVIEWABLE.has(r.run_type)), voting: sum((r) => r.run_type === "proxy_voting") });
        setRecentRuns([...runs].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)).slice(0, 50));
      })
      .catch(() => setWaiting(null));
    api.getStewardshipFlow("house").then(
      (flow) => setOpenDecisions(stageDecisions(flow)),
      () => setOpenDecisions(0),
    );
  }, [route, decidedAt]);

  const hub = hubOf(active);
  // The tab title names the screen, for browser tabs and screen readers.
  useEffect(() => {
    document.title = `${hub?.label ?? TABS.find((t) => t.id === active)!.label} · ARP`;
  }, [active, hub]);

  const pendingReview =
    active === "review" && route.params.length === 2 && REVIEWABLE.has(route.params[0])
      ? { kind: route.params[0] as ReviewableRunKind, runId: route.params[1] }
      : null;

  const [paletteOpen, setPaletteOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Below 1024px the sidebar is an off-canvas drawer; on desktop navOpen is
  // ignored by the CSS.
  const [navOpen, setNavOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!navOpen) return;
    const menu = menuRef.current;
    navRef.current?.querySelector<HTMLElement>(".nav-tab.active")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setNavOpen(false);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      menu?.focus();
    };
  }, [navOpen]);

  function go(id: TabId) {
    navigate(id);
    setNavOpen(false);
  }

  const sendUniverse = (from: string) => (to: "extraction" | "transitionPlan" | "discovery", path: string, count: number) => {
    setHandoff({ path, count, from, to });
    navigate(to);
  };

  function sendToTheme(taxonomyId: string) {
    setPendingTaxonomyId(taxonomyId);
    navigate("theme");
  }

  function openReview(kind: ReviewableRunKind, runId: string) {
    navigate("review", kind, runId);
  }

  return (
    <div className={navOpen ? "app-shell nav-open" : "app-shell"}>
      {/* Routing lives in the hash, so the skip link focuses <main> instead of
          following an in-page anchor. */}
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      <div id="announcer" className="visually-hidden" role="status" aria-live="polite" />
      <header className="app-topbar">
        <button
          ref={menuRef}
          className="app-topbar-menu"
          aria-label="Open navigation"
          aria-expanded={navOpen}
          aria-controls="app-sidebar"
          onClick={() => setNavOpen(true)}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round">
            <path d="M4 7h16M4 12h16M4 17h16" />
          </svg>
        </button>
        <span className="app-sidebar-mark">A</span>
        <span className="app-topbar-title">{TABS.find((t) => t.id === active)!.label}</span>
      </header>
      <div className="nav-scrim" onClick={() => setNavOpen(false)} />
      <aside className="app-sidebar" id="app-sidebar" ref={navRef}>
        <div className="app-sidebar-brand">
          <span className="app-sidebar-mark">A</span>
          <span className="app-sidebar-wordmark">ARP</span>
        </div>
        <div className="app-sidebar-reviewer">
          <SignedInAs />
        </div>
        <button className="palette-trigger" onClick={() => setPaletteOpen(true)}>
          Jump to…
          <kbd>{/Mac|iPhone|iPad/.test(navigator.userAgent) ? "⌘K" : "Ctrl K"}</kbd>
        </button>
        <ThemeSwitch />
        <nav className="app-nav">
          {NAV_GROUPS.map((group, i) => {
            const links = group.ids.map((id) => {
              const t = TABS.find((tab) => tab.id === id)!;
              const h = hubOf(id);
              const current = h ? h.tabs.some(([tid]) => tid === active) : id === navIdOf(active);
              const count = id === "stewardship" ? openDecisions : waiting && (id === "review" || id === "voting") ? waiting[id] : 0;
              return (
                <a
                  key={t.id}
                  href={`#/${t.id}`}
                  className={current ? "nav-tab active" : "nav-tab"}
                  aria-current={current ? "page" : undefined}
                  onClick={() => setNavOpen(false)}
                >
                  <span className="nav-tab-icon">{NAV_ICONS[t.id]}</span>
                  <span className="nav-tab-label">{h?.label ?? t.label}</span>
                  {count > 0 && (
                    <span className="nav-count" aria-label={`${count} ${count === 1 ? "decision" : "decisions"} waiting on you`}>
                      {count}
                    </span>
                  )}
                </a>
              );
            });
            if (group.collapsed) {
              return (
                <details className="nav-more" key={group.label} open={group.ids.includes(navIdOf(active)) || undefined}>
                  <summary className="nav-group-label">{group.label}</summary>
                  <div className="nav-group">{links}</div>
                </details>
              );
            }
            return (
              <div className="nav-group" key={group.label ?? `group-${i}`}>
                {group.label && <div className="nav-group-label">{group.label}</div>}
                {links}
              </div>
            );
          })}
        </nav>
      </aside>
      {paletteOpen && <CommandPalette items={[...PALETTE_ITEMS, ...recentRuns.map(runItem)]} onClose={() => setPaletteOpen(false)} />}
      <main className="app-main" id="main" tabIndex={-1}>
        <ProcessBar tab={active} sub={route.params[0]} />
        {hub && (
          <nav className="sub-nav hub-nav" aria-label={hub.label}>
            {hub.tabs.map(([id, label]) => (
              <a key={id} href={`#/${id}`} className={id === active ? "nav-tab active" : "nav-tab"} aria-current={id === active ? "page" : undefined}>
                {label}
              </a>
            ))}
          </nav>
        )}
        {active === "home" && <StartPage />}
        {(active === "stewardiq" || active === "themeMachine" || active === "designStudio") && <ProcessOverview key={active} id={active} />}
        {active === "dashboard" && <MonitoringDashboard onNavigate={go} onOpenReview={openReview} />}
        {active === "processes" && <Processes selected={route.params[0] ?? null} onSelect={(id) => navigate("processes", id)} />}
        {active === "search" && <Search />}
        {active === "arcade" && <Arcade selected={route.params[0] ?? null} />}
        {active === "theme" && <ThemeBuilder onSendToExtraction={(path, count) => sendUniverse("Thematic Universe")("extraction", path, count)} pendingTaxonomyId={pendingTaxonomyId} />}
        {active === "taxonomy" && <TaxonomyLibrary onUseInTheme={sendToTheme} />}
        {active === "emergingThemes" && <EmergingThemesDetector onNavigate={go} />}
        {active === "backgroundAgents" && <BackgroundAgents />}
        {active === "extraction" && <Extraction key="extraction" pendingUniverse={pendingFor("extraction")} />}
        {active === "transitionPlan" && <Extraction key="transitionPlan" initialProfile="transition_plan" pendingUniverse={pendingFor("transitionPlan")} />}
        {active === "transitionBarrier" && <TransitionBarrierAssessment />}
        {active === "identity" && <IdentityResolution onSendToDiscovery={(path, count) => sendUniverse("Identity Resolution")("discovery", path, count)} />}
        {active === "discovery" && <DocumentDiscovery pendingUniverse={pendingFor("discovery")} onSendUniverse={sendUniverse("Document Discovery")} />}
        {active === "portfolio-monitoring" && <PortfolioRiskMonitoringTool key={route.params[0]} initialSub={route.params[0]} onSendUniverse={sendUniverse("Risk Monitoring")} />}
        {active === "review" && <ReviewQueue key={pendingReview ? `${pendingReview.kind}/${pendingReview.runId}` : "review"} pendingReview={pendingReview} />}
        {active === "history" && <RunHistory onOpenReview={openReview} />}
        {active === "stewardship" && <StewardWorkflow initialTab={route.params[0]} />}
        {active === "engagement" && <EngagementDashboard />}
        {active === "voting" && <VotingRuns selectedRunId={route.params[0] ?? null} onSelectRun={(id) => navigate("voting", id)} />}
        {active === "reporting" && <ReportBuilder />}
        {active === "strategyReplication" && <StrategyReplication />}
        {active === "decision" && <DecisionStudio />}
        {active === "index" && <IndexBuilder />}
        {active === "library" && <DataLibrary />}
      </main>
    </div>
  );
}

export default App;
