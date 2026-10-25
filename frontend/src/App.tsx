import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { canLeave } from "./lib/leaveGuard";
import { ReviewerField } from "./components/ReviewerField";
import { SignedInAs } from "./components/SignedInAs";
import { ProcessBar, StartPage, WorkspaceOverview } from "./pages/ProcessHub";
import { ArgusFlow } from "./pages/ArgusFlow";
import { ArgusStart } from "./pages/ArgusStart";
import { WORKSPACES, workspaceOfProcess, type WorkspaceId } from "./lib/processes";
import { STAGE_TABS } from "./pages/steward/common";
import { SUB_TABS as RISK_TABS } from "./lib/subTabs";
import { CommandPalette, type PaletteItem } from "./components/CommandPalette";
import { AskPanel } from "./components/AskPanel";
import { clearTurns, loadTurns, saveTurns, type AskTurn } from "./lib/askHistory";
import { useMe } from "./lib/reviewer";
import { ThemeSwitch } from "./components/ThemeSwitch";
import { NAV_ICONS } from "./components/NavIcons";
import type { ReviewableRunKind, RunManifest, UniverseHandoff } from "./types";
import { REVIEWABLE_RUN_TYPES, runTypeLabel } from "./lib/runs";
import { listAllRuns } from "./lib/poll";
import { HUBS, NAV_GROUPS, currentNavIds, navCount, redirectHash } from "./lib/nav";

// Pages load on demand so the first screen does not ship every page and its editors.
const ThemeBuilder = lazy(() => import("./pages/ThemeBuilder").then((x) => ({ default: x.ThemeBuilder })));
const Extraction = lazy(() => import("./pages/Extraction").then((x) => ({ default: x.Extraction })));
const TransitionBarrierAssessment = lazy(() => import("./pages/TransitionBarrierAssessment").then((x) => ({ default: x.TransitionBarrierAssessment })));
const EmergingThemesDetector = lazy(() => import("./pages/EmergingThemesDetector").then((x) => ({ default: x.EmergingThemesDetector })));
const ReviewQueue = lazy(() => import("./pages/ReviewQueue").then((x) => ({ default: x.ReviewQueue })));
const RunHistory = lazy(() => import("./pages/RunHistory").then((x) => ({ default: x.RunHistory })));
const DataLibrary = lazy(() => import("./pages/DataLibrary").then((x) => ({ default: x.DataLibrary })));
const TaxonomyLibrary = lazy(() => import("./pages/TaxonomyLibrary").then((x) => ({ default: x.TaxonomyLibrary })));
const BackgroundAgents = lazy(() => import("./pages/BackgroundAgents").then((x) => ({ default: x.BackgroundAgents })));
const EngagementDashboard = lazy(() => import("./pages/EngagementDashboard").then((x) => ({ default: x.EngagementDashboard })));
const VotingRuns = lazy(() => import("./pages/VotingRuns").then((x) => ({ default: x.VotingRuns })));
const StewardWorkflow = lazy(() => import("./pages/StewardWorkflow").then((x) => ({ default: x.StewardWorkflow })));
const PortfolioRiskMonitoringTool = lazy(() => import("./pages/PortfolioRiskMonitoringTool").then((x) => ({ default: x.PortfolioRiskMonitoringTool })));
const ReportBuilder = lazy(() => import("./pages/ReportBuilder").then((x) => ({ default: x.ReportBuilder })));
const StrategyReplication = lazy(() => import("./pages/StrategyReplication").then((x) => ({ default: x.StrategyReplication })));
const SignalsWorkbench = lazy(() => import("./pages/SignalsWorkbench").then((x) => ({ default: x.SignalsWorkbench })));
const ValueChainExplorer = lazy(() => import("./pages/value-chain/ValueChainExplorer").then((x) => ({ default: x.ValueChainExplorer })));
const Search = lazy(() => import("./pages/Search").then((x) => ({ default: x.Search })));
const SecurityMaster = lazy(() => import("./pages/SecurityMaster").then((x) => ({ default: x.SecurityMaster })));
const Feeds = lazy(() => import("./pages/Feeds").then((x) => ({ default: x.Feeds })));
const Issues = lazy(() => import("./pages/Issues").then((x) => ({ default: x.Issues })));
const SmartSearch = lazy(() => import("./pages/SmartSearch").then((x) => ({ default: x.SmartSearch })));
const Outputs = lazy(() => import("./pages/Outputs").then((x) => ({ default: x.Outputs })));
const Arcade = lazy(() => import("./pages/Arcade").then((x) => ({ default: x.Arcade })));
const DecisionStudio = lazy(() => import("./pages/DecisionStudio").then((x) => ({ default: x.DecisionStudio })));
const IndexBuilder = lazy(() => import("./pages/IndexBuilder").then((x) => ({ default: x.IndexBuilder })));
const ArgusUniverse = lazy(() => import("./pages/ArgusUniverse").then((x) => ({ default: x.ArgusUniverse })));
const Company = lazy(() => import("./pages/Company").then((x) => ({ default: x.Company })));
const XbrlFacts = lazy(() => import("./pages/XbrlFacts").then((x) => ({ default: x.XbrlFacts })));
const ThemeDossiers = lazy(() => import("./pages/ThemeDossiers").then((x) => ({ default: x.ThemeDossiers })));
const RfpAnswers = lazy(() => import("./pages/RfpAnswers").then((x) => ({ default: x.RfpAnswers })));

const TABS = [
  { id: "home", label: "Start" },
  { id: "stewardiq", label: "StewardIQ" },
  { id: "argus", label: "Argus" },
  { id: "argusUniverse", label: "Universe" },
  { id: "transitionIntel", label: "Transition Intelligence Platform" },
  { id: "rdLab", label: "R&D Lab" },
  { id: "dataHub", label: "Data Hub" },
  { id: "search", label: "Search" },
  { id: "securityMaster", label: "Security Master" },
  { id: "feeds", label: "Feeds" },
  { id: "issues", label: "Issues" },
  { id: "smartSearch", label: "Smart Search" },
  { id: "outputs", label: "Outputs" },
  { id: "theme", label: "Thematic Universe" },
  { id: "taxonomy", label: "Taxonomy Library" },
  { id: "emergingThemes", label: "Emerging Themes" },
  { id: "themes", label: "Theme dossiers" },
  { id: "backgroundAgents", label: "Background Agents" },
  { id: "extraction", label: "Extraction" },
  { id: "transitionPlan", label: "Transition Plan" },
  { id: "transitionBarrier", label: "Transition Barriers" },
  { id: "portfolio-monitoring", label: "Risk Monitoring" },
  { id: "review", label: "Review Queue" },
  { id: "history", label: "Run History" },
  { id: "stewardship", label: "Steward Workflow" },
  { id: "engagement", label: "Engagement" },
  { id: "voting", label: "Proxy Voting" },
  { id: "reporting", label: "Presentations & Reports" },
  { id: "strategyReplication", label: "Strategy Replication" },
  { id: "signals", label: "Signals workbench" },
  { id: "valueChain", label: "Value Chain Explorer" },
  { id: "decision", label: "Decision Studio" },
  { id: "index", label: "Index Construction" },
  { id: "xbrl", label: "XBRL Facts" },
  { id: "rfp", label: "RFP Answers" },
  { id: "library", label: "Data Library" },
  { id: "arcade", label: "Arcade" },
  // Reached from company names elsewhere (#/companies/<ref>) and the palette; not in the sidebar.
  { id: "companies", label: "Company" },
] as const;

type TabId = (typeof TABS)[number]["id"];

const hubOf = (id: TabId) => HUBS.find((h) => h.tabs.some(([t]) => t === id));
const isWorkspace = (id: string): id is WorkspaceId => WORKSPACES.some((w) => w.id === id);

// Everything the command palette can jump to: every screen (under its hub's
// name where it has one), plus the Steward stages and Risk Monitoring tabs.
const PALETTE_ITEMS: PaletteItem[] = [
  ...TABS.map((t) => ({ label: t.label, hint: hubOf(t.id)?.label.replace(t.label, "") || undefined, href: `#/${t.id}` })),
  ...STAGE_TABS.map((t) => ({ label: t.label, hint: "Steward Workflow", href: `#/stewardship/${t.id}` })),
  ...RISK_TABS.map((t) => ({ label: t.label, hint: "Risk Monitoring", href: `#/portfolio-monitoring/${t.id}` })),
];

/** A run in the palette opens where its decisions are made, else in Run History. */
const runItem = (r: RunManifest): PaletteItem => ({
  label: `${runTypeLabel(r.run_type)} ${r.run_id}`,
  hint: "Run",
  href: r.run_type === "proxy_voting" ? `#/voting/${r.run_id}` : REVIEWABLE_RUN_TYPES.has(r.run_type) ? `#/review/${r.run_type}/${r.run_id}` : "#/history",
});

/** The URL is the source of truth for where you are: `#/<tab>/<param>...`,
 * so refresh, Back and a pasted link all land on the same view -- e.g.
 * `#/voting/<run id>` or `#/review/extraction/<run id>`. */
function parseHash(hash = window.location.hash): { tab: TabId; params: string[] } {
  const [tab, ...params] = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  // Old links: the Theme Machine and Design Studio boxes merged into R&D Lab;
  // the Processes screen's processes now live on their workspace pages.
  if (tab === "themeMachine" || tab === "designStudio") return { tab: "rdLab", params: [] };
  if (tab === "processes") return { tab: workspaceOfProcess(params[0])?.id ?? "home", params: [] };
  return TABS.some((t) => t.id === tab) ? { tab: tab as TabId, params } : { tab: "home", params: [] };
}

/** The route for the current URL, after replacing a removed screen's link with
 * its replacement (replaceState, so Back never returns to the dead route). */
function readRoute() {
  const target = redirectHash(window.location.hash);
  if (target) history.replaceState(null, "", target);
  return parseHash();
}

const mac = /Mac|iPhone|iPad/.test(navigator.userAgent);

function navigate(tab: TabId, ...params: string[]) {
  window.location.hash = "/" + [tab, ...params].map(encodeURIComponent).join("/");
}

/** ARP mark: a pixel "A"; the apex square is the signal, where a person ratifies. */
function ArpMark() {
  return (
    <svg className="app-sidebar-mark" viewBox="0 0 62 62" aria-hidden="true">
      <path fill="currentColor" d="M14 2h10v10H14zM38 2h10v10H38zM2 14h10v10H2zM50 14h10v10H50zM2 26h10v10H2zM14 26h10v10H14zM26 26h10v10H26zM38 26h10v10H38zM50 26h10v10H50zM2 38h10v10H2zM50 38h10v10H50zM2 50h10v10H2zM50 50h10v10H50z" />
      <rect x="26" y="2" width="10" height="10" fill="var(--hi)" />
    </svg>
  );
}

function App() {
  const [route, setRoute] = useState(readRoute);
  const active = route.tab;
  const [waiting, setWaiting] = useState<{ review: number } | null>(null);
  const [recentRuns, setRecentRuns] = useState<RunManifest[]>([]);
  // One universe in flight between screens, addressed to one of them.
  const [handoff, setHandoff] = useState<(UniverseHandoff & { to: TabId }) | null>(null);
  const pendingFor = (to: TabId) => (handoff?.to === to ? handoff : null);
  const [pendingTaxonomyId, setPendingTaxonomyId] = useState<string | null>(null);

  // The hash last shown, so a navigation the open screen refuses can be put back.
  const shownHash = useRef(window.location.hash);
  useEffect(() => {
    const onHash = () => {
      const next = readRoute();
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
    listAllRuns()
      .then((runs) => {
        const sum = (keep: (r: RunManifest) => boolean) => runs.filter(keep).reduce((n, r) => n + r.review_count, 0);
        setWaiting({ review: sum((r) => REVIEWABLE_RUN_TYPES.has(r.run_type)) });
        setRecentRuns([...runs].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)).slice(0, 50));
      })
      .catch(() => setWaiting(null));
  }, [route, decidedAt]);

  const hub = hubOf(active);
  // The tab title names the screen, for browser tabs and screen readers.
  useEffect(() => {
    document.title = `${hub?.label ?? TABS.find((t) => t.id === active)!.label} · ARP`;
  }, [active, hub]);

  const pendingReview =
    active === "review" && route.params.length === 2 && REVIEWABLE_RUN_TYPES.has(route.params[0])
      ? { kind: route.params[0] as ReviewableRunKind, runId: route.params[1] }
      : null;

  const [paletteOpen, setPaletteOpen] = useState(false);
  const me = useMe();
  const canAsk = me != null && me.role !== "viewer";
  const [askOpen, setAskOpen] = useState(false);
  const [askTurns, setAskTurns] = useState<AskTurn[]>(() => loadTurns());
  const askSideRef = useRef<HTMLButtonElement>(null);
  const askTopRef = useRef<HTMLButtonElement>(null);
  useEffect(() => saveTurns(askTurns), [askTurns]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(true);
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j" && canAsk) {
        e.preventDefault();
        setAskOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canAsk]);
  function closeAsk() {
    setAskOpen(false);
    // The sidebar is a closed drawer at 1024px and below, so focus goes to the top-bar button there.
    const narrow = window.matchMedia("(max-width: 1024px)").matches;
    (narrow ? askTopRef : askSideRef).current?.focus();
  }

  // Below 1024px the sidebar is an off-canvas drawer; on desktop navOpen is
  // ignored by the CSS.
  const [navOpen, setNavOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!navOpen) return;
    const menu = menuRef.current;
    // Most screens have no sidebar link; then focus the first one so the drawer still takes focus.
    (navRef.current?.querySelector<HTMLElement>(".nav-tab.active") ?? navRef.current?.querySelector<HTMLElement>(".nav-tab"))?.focus();
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

  const sendUniverse = (from: string) => (to: "extraction" | "transitionPlan" | "xbrl", path: string, count: number) => {
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
        <ArpMark />
        <span className="app-topbar-title">{TABS.find((t) => t.id === active)!.label}</span>
        {canAsk && (
          <button ref={askTopRef} className="app-topbar-ask" aria-expanded={askOpen} onClick={() => setAskOpen(true)}>
            Ask
          </button>
        )}
      </header>
      <div className="nav-scrim" onClick={() => setNavOpen(false)} />
      <aside className="app-sidebar" id="app-sidebar" ref={navRef}>
        <div className="app-sidebar-brand">
          <ArpMark />
          <span className="app-sidebar-wordmark">ARP</span>
        </div>
        <div className="app-sidebar-reviewer">
          {/* The not-verified note is repeated where a typed name confirms a decision. */}
          <ReviewerField hint={false} />
          <SignedInAs />
        </div>
        <div className="sidebar-actions">
          <button className="palette-trigger" title={mac ? "⌘K" : "Ctrl K"} aria-keyshortcuts="Control+K Meta+K" onClick={() => setPaletteOpen(true)}>
            Jump to…
          </button>
          {canAsk && (
            <button ref={askSideRef} className="palette-trigger" title={mac ? "⌘J" : "Ctrl J"} aria-keyshortcuts="Control+J Meta+J" aria-expanded={askOpen} onClick={() => { setNavOpen(false); setAskOpen(true); }}>
              Ask ARP
            </button>
          )}
        </div>
        <nav className="app-nav">
          {NAV_GROUPS.map((group, i) => {
            const links = group.ids.map((id) => {
              const t = TABS.find((tab) => tab.id === id)!;
              const current = currentNavIds(active).includes(id);
              const count = navCount(id, waiting);
              return (
                <a
                  key={t.id}
                  href={`#/${t.id}`}
                  className={current ? "nav-tab active" : "nav-tab"}
                  aria-current={current ? "page" : undefined}
                  onClick={() => setNavOpen(false)}
                >
                  <span className="nav-tab-icon">{NAV_ICONS[t.id]}</span>
                  <span className="nav-tab-label">{t.label}</span>
                  {count > 0 && (
                    <span className="nav-count" aria-label={`${count} ${count === 1 ? "decision" : "decisions"} waiting on you`}>
                      {count}
                    </span>
                  )}
                </a>
              );
            });
            return (
              <div className="nav-group" key={group.label ?? `group-${i}`}>
                {group.label && <div className="nav-group-label">{group.label}</div>}
                {links}
              </div>
            );
          })}
        </nav>
        <ThemeSwitch />
      </aside>
      {askOpen && canAsk && (
        <AskPanel turns={askTurns} setTurns={setAskTurns} onClose={closeAsk} onClear={() => { clearTurns(); setAskTurns([]); }} />
      )}
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
        <Suspense fallback={<p className="muted" role="status">Loading…</p>}>
        {active === "home" && <StartPage />}
        {active === "argus" && (route.params[0] ? <ArgusFlow key={route.params[0]} flowId={route.params[0]} step={Number(route.params[1] ?? 1) || 1} onSendUniverse={sendUniverse("Argus")} /> : <ArgusStart />)}
        {isWorkspace(active) && active !== "argus" && <WorkspaceOverview key={active} id={active} />}
        {active === "search" && <Search />}
        {active === "securityMaster" && <SecurityMaster />}
        {active === "feeds" && <Feeds />}
        {active === "issues" && <Issues />}
        {active === "smartSearch" && <SmartSearch />}
        {active === "outputs" && <Outputs />}
        {active === "arcade" && <Arcade selected={route.params[0] ?? null} />}
        {active === "theme" && <ThemeBuilder key={route.params[0]} initialRunId={route.params[0] ?? null} onSendToExtraction={(path, count) => sendUniverse("Thematic Universe")("extraction", path, count)} pendingTaxonomyId={pendingTaxonomyId} />}
        {active === "taxonomy" && <TaxonomyLibrary onUseInTheme={sendToTheme} />}
        {active === "emergingThemes" && <EmergingThemesDetector onNavigate={go} />}
        {active === "themes" && <ThemeDossiers params={route.params} onFindCompanies={sendToTheme} />}
        {active === "backgroundAgents" && <BackgroundAgents />}
        {active === "extraction" && <Extraction key="extraction" initialTab={route.params[0]} initialAuto={route.params[1] === "auto"} pendingUniverse={pendingFor("extraction")} />}
        {active === "transitionPlan" && <Extraction key="transitionPlan" initialProfile="transition_plan" pendingUniverse={pendingFor("transitionPlan")} />}
        {active === "transitionBarrier" && <TransitionBarrierAssessment params={route.params} />}
        {active === "portfolio-monitoring" && <PortfolioRiskMonitoringTool key={route.params[0]} initialSub={route.params[0]} onSendUniverse={sendUniverse("Risk Monitoring")} />}
        {active === "review" && <ReviewQueue key={pendingReview ? `${pendingReview.kind}/${pendingReview.runId}` : "review"} pendingReview={pendingReview} />}
        {active === "history" && <RunHistory onOpenReview={openReview} />}
        {active === "stewardship" && <StewardWorkflow initialTab={route.params[0]} />}
        {active === "engagement" && <EngagementDashboard />}
        {active === "voting" && <VotingRuns selectedRunId={route.params[0] ?? null} onSelectRun={(id) => navigate("voting", id)} />}
        {active === "reporting" && <ReportBuilder />}
        {active === "strategyReplication" && <StrategyReplication />}
        {active === "signals" && <SignalsWorkbench />}
        {active === "valueChain" && <ValueChainExplorer key={route.params.join("/")} params={route.params} />}
        {active === "decision" && <DecisionStudio key={route.params.join("/")} initialSource={route.params[0]} initialRunId={route.params[1]} />}
        {active === "index" && <IndexBuilder />}
        {active === "argusUniverse" && <ArgusUniverse onSendUniverse={sendUniverse("Argus Universe")} />}
        {active === "rfp" && <RfpAnswers projectId={route.params[0] ? Number(route.params[0]) : null} onOpen={(id) => (id === null ? navigate("rfp") : navigate("rfp", String(id)))} />}
        {active === "xbrl" && <XbrlFacts pendingUniverse={pendingFor("xbrl")} selectedRunId={route.params[0] ?? null} onSelectRun={(id) => navigate("xbrl", id)} />}
        {active === "library" && <DataLibrary />}
        {active === "companies" && <Company companyRef={route.params[0]} />}
        </Suspense>
      </main>
    </div>
  );
}

export default App;
