import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { canLeave } from "./lib/leaveGuard";
import { ProcessBar, StartPage, WorkspaceOverview } from "./pages/ProcessHub";
import { ArgusFlow } from "./pages/ArgusFlow";
import { singleFlight, stepFromUrl } from "./lib/argusFlow";
import { ArgusNew, ArgusStart, openNewFlow } from "./pages/ArgusStart";
import { WORKSPACES, workspaceOfProcess, type WorkspaceId } from "./lib/processes";
import { STAGE_TABS } from "./pages/steward/common";
import { SUB_TABS as RISK_TABS } from "./lib/subTabs";
import { CommandPalette, type PaletteItem } from "./components/CommandPalette";
import { AskPanel } from "./components/AskPanel";
import { clearTurns, loadTurns, saveTurns, type AskTurn } from "./lib/askHistory";
import { useMe } from "./lib/reviewer";
import { AppTopbar } from "./components/AppTopbar";
import { WorkspaceRow } from "./components/WorkspaceRow";
import type { ReviewableRunKind, RunManifest, WaitingCounts } from "./types";
import { REVIEWABLE_RUN_TYPES, runTypeLabel } from "./lib/runs";
import { api } from "./api/client";
import { listAllRuns } from "./lib/poll";
import { HUBS, entryTab, redirectHash, splitHash } from "./lib/nav";
import { refineTarget } from "./lib/refine";
import { Landing } from "./pages/Landing";

// Pages load on demand so the first screen does not ship every page and its editors.
const ThemeBuilder = lazy(() => import("./pages/ThemeBuilder").then((x) => ({ default: x.ThemeBuilder })));
const TransitionBarrierAssessment = lazy(() => import("./pages/TransitionBarrierAssessment").then((x) => ({ default: x.TransitionBarrierAssessment })));
const EmergingThemesDetector = lazy(() => import("./pages/EmergingThemesDetector").then((x) => ({ default: x.EmergingThemesDetector })));
const ReviewQueue = lazy(() => import("./pages/ReviewQueue").then((x) => ({ default: x.ReviewQueue })));
const RunHistory = lazy(() => import("./pages/RunHistory").then((x) => ({ default: x.RunHistory })));
const DataLibrary = lazy(() => import("./pages/DataLibrary").then((x) => ({ default: x.DataLibrary })));
const AuthorityTaxonomyRun = lazy(() => import("./pages/AuthorityTaxonomyRun").then((x) => ({ default: x.AuthorityTaxonomyRun })));
const TaxonomyLibrary = lazy(() => import("./pages/TaxonomyLibrary").then((x) => ({ default: x.TaxonomyLibrary })));
const BackgroundAgents = lazy(() => import("./pages/BackgroundAgents").then((x) => ({ default: x.BackgroundAgents })));
const EngagementDashboard = lazy(() => import("./pages/EngagementDashboard").then((x) => ({ default: x.EngagementDashboard })));
const VotingRuns = lazy(() => import("./pages/VotingRuns").then((x) => ({ default: x.VotingRuns })));
const StewardCockpit = lazy(() => import("./pages/StewardCockpit").then((x) => ({ default: x.StewardCockpit })));
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
const ArgusWalkthrough = lazy(() => import("./pages/ArgusWalkthrough").then((x) => ({ default: x.ArgusWalkthrough })));
const Company = lazy(() => import("./pages/Company").then((x) => ({ default: x.Company })));
const XbrlFacts = lazy(() => import("./pages/XbrlFacts").then((x) => ({ default: x.XbrlFacts })));
const DesignStrategy = lazy(() => import("./pages/DesignStrategy").then((x) => ({ default: x.DesignStrategy })));
const ThemeDossiers = lazy(() => import("./pages/ThemeDossiers").then((x) => ({ default: x.ThemeDossiers })));
const Agent = lazy(() => import("./pages/Agent").then((x) => ({ default: x.Agent })));
const RfpAnswers = lazy(() => import("./pages/RfpAnswers").then((x) => ({ default: x.RfpAnswers })));
const Refine = lazy(() => import("./pages/Refine").then((x) => ({ default: x.Refine })));

const TABS = [
  { id: "home", label: "Start" },
  { id: "stewardiq", label: "StewardIQ" },
  { id: "argus", label: "Argus" },
  { id: "argusWalkthrough", label: "Walkthrough" },
  { id: "transitionIntel", label: "Transition Intel" },
  { id: "rdLab", label: "Strategy" },
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
  { id: "designStrategy", label: "Design a strategy" },
  { id: "backgroundAgents", label: "Background Agents" },
  { id: "transitionBarrier", label: "Transition Barriers" },
  { id: "portfolio-monitoring", label: "Risk Monitoring" },
  { id: "review", label: "Needs you" },
  { id: "history", label: "Run History" },
  { id: "agent", label: "Agent" },
  { id: "stewardship", label: "Steward Workflow" },
  { id: "engagement", label: "Engagement" },
  { id: "voting", label: "Proxy Voting" },
  { id: "reporting", label: "Presentations & Reports" },
  { id: "strategyReplication", label: "Strategy Replication" },
  { id: "signals", label: "Signals workbench" },
  { id: "valueChain", label: "Value Chain Explorer" },
  { id: "decision", label: "Decision Studio" },
  { id: "index", label: "Portfolio Builder" },
  { id: "xbrl", label: "XBRL Facts" },
  { id: "rfp", label: "RFP Answers" },
  { id: "refine", label: "Refine" },
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
  const { tab, params } = splitHash(hash);
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

function navigate(tab: TabId, ...params: string[]) {
  window.location.hash = "/" + [tab, ...params].map(encodeURIComponent).join("/");
}

function App() {
  const [route, setRoute] = useState(readRoute);
  const active = route.tab;
  const [waiting, setWaiting] = useState<WaitingCounts | null>(null);
  const [recentRuns, setRecentRuns] = useState<RunManifest[]>([]);
  const [pendingTaxonomyId, setPendingTaxonomyId] = useState<string | null>(null);

  // The hash last shown, so a navigation the open screen refuses can be put back.
  const shownHash = useRef(window.location.hash);
  useEffect(() => {
    const onHash = () => {
      const next = readRoute();
      // Any change of address remounts a guarded screen (its key is its params), so even a link to the same tab asks.
      if (window.location.hash !== shownHash.current && !canLeave()) {
        // hashchange cannot be cancelled; replaceState restores the URL without firing it again.
        history.replaceState(null, "", shownHash.current || "#");
        return;
      }
      shownHash.current = window.location.hash;
      setRoute(next);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // An announcement belongs to the screen it was made on: another screen starts with an empty live region.
  useEffect(() => {
    const el = document.getElementById("announcer");
    if (el) el.textContent = "";
  }, [active]);

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
    api.getWaiting().then(setWaiting, () => setWaiting(null));
    listAllRuns()
      .then((runs) => setRecentRuns([...runs].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)).slice(0, 50)))
      .catch(() => {});
  }, [route, decidedAt]);

  const hub = hubOf(active);
  // route changes on every hashchange, so this re-reads the tab's query (e.g. #/refine?report=R) with it.
  const refine = refineTarget(splitHash(window.location.hash).query);
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
  const [askPending, setAskPending] = useState<{ id: number; question: string } | null>(null);
  const searchRef = useRef<HTMLButtonElement>(null);
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
    searchRef.current?.focus();
  }

  function go(id: TabId) {
    navigate(id);
  }

  // A hand-over opens step 1 of a new Argus flow with the companies listed; the Transition Plan one also picks that template.
  // One hand-over at a time: a double click on "Argus →" must not start two flows.
  const sendToArgus = useRef(singleFlight((to: "argus" | "transitionPlan", path: string) =>
    openNewFlow({ universePath: path, preset: to === "transitionPlan" ? "transition_plan" : null }))).current;

  function sendToTheme(taxonomyId: string) {
    setPendingTaxonomyId(taxonomyId);
    navigate("theme");
  }

  function openReview(kind: ReviewableRunKind, runId: string) {
    navigate("review", kind, runId);
  }

  return (
    <div className="app-shell app-shell-start">
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
      <AppTopbar
        active={active}
        canAsk={canAsk}
        searchRef={searchRef}
        waiting={waiting}
        onSearch={() => setPaletteOpen(true)}
      />
      <WorkspaceRow hash={window.location.hash} />
      {askOpen && canAsk && (
        <AskPanel turns={askTurns} setTurns={setAskTurns} onClose={closeAsk} onClear={() => { clearTurns(); setAskTurns([]); }} pending={askPending} />
      )}
      {paletteOpen && (
        <CommandPalette
          items={[...PALETTE_ITEMS, ...recentRuns.map(runItem)]}
          onClose={() => setPaletteOpen(false)}
          onAsk={canAsk ? (question) => { setAskPending({ id: Date.now(), question }); setAskOpen(true); } : undefined}
        />
      )}
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
        {active === "argus" && route.params[0] === "new" && <ArgusNew preset={route.params[1] ?? null} />}
        {active === "argus" && route.params[0] !== "new" && (route.params[0] ? <ArgusFlow key={route.params[0]} flowId={route.params[0]} step={stepFromUrl(route.params[1])} /> : <ArgusStart />)}
        {isWorkspace(active) && active !== "argus" && !(active === "stewardiq" && route.params[0] === "cockpit") && <WorkspaceOverview key={active} id={active} />}
        {active === "stewardiq" && route.params[0] === "cockpit" && <StewardCockpit key={route.params[1] ?? "today"} asOf={route.params[1]} />}
        {active === "search" && <Search />}
        {active === "securityMaster" && <SecurityMaster />}
        {active === "feeds" && <Feeds />}
        {active === "issues" && <Issues />}
        {active === "smartSearch" && <SmartSearch />}
        {active === "outputs" && <Outputs />}
        {active === "arcade" && <Arcade selected={route.params[0] ?? null} />}
        {active === "theme" && <ThemeBuilder key={route.params[0]} initialRunId={route.params[0] ?? null} onSendToArgus={(path) => sendToArgus("argus", path)} pendingTaxonomyId={pendingTaxonomyId} />}
        {active === "taxonomy" && route.params[0] === "authority" && <AuthorityTaxonomyRun key={route.params[1] ?? "new"} runId={route.params[1]} />}
        {active === "taxonomy" && route.params[0] !== "authority" && <TaxonomyLibrary onUseInTheme={sendToTheme} />}
        {active === "emergingThemes" && <EmergingThemesDetector onNavigate={go} />}
        {active === "designStrategy" && <DesignStrategy />}
        {active === "themes" && <ThemeDossiers params={route.params} onFindCompanies={sendToTheme} />}
        {active === "backgroundAgents" && <BackgroundAgents />}
        {active === "transitionBarrier" && <TransitionBarrierAssessment params={route.params} />}
        {active === "portfolio-monitoring" && <PortfolioRiskMonitoringTool key={route.params[0]} initialSub={route.params[0]} onSendUniverse={sendToArgus} />}
        {active === "review" && <ReviewQueue key={pendingReview ? `${pendingReview.kind}/${pendingReview.runId}` : "review"} pendingReview={pendingReview} waiting={waiting} />}
        {active === "history" && <RunHistory onOpenReview={openReview} focusRunId={route.params[0] ?? null} />}
        {active === "agent" && <Agent selectedId={route.params[0] ?? null} onSelect={(id) => navigate("agent", id)} />}
        {active === "stewardship" && <StewardWorkflow initialTab={route.params[0]} />}
        {active === "engagement" && <EngagementDashboard />}
        {active === "voting" && <VotingRuns selectedRunId={route.params[0] ?? null} onSelectRun={(id) => navigate("voting", id)} />}
        {active === "reporting" && <ReportBuilder />}
        {active === "strategyReplication" && <StrategyReplication />}
        {active === "signals" && <SignalsWorkbench />}
        {active === "valueChain" && <ValueChainExplorer key={route.params.join("/")} params={route.params} />}
        {active === "decision" && <DecisionStudio key={route.params.join("/")} initialSource={route.params[0]} initialRunId={route.params[1]} />}
        {active === "index" && <IndexBuilder />}
        {active === "argusWalkthrough" && <ArgusWalkthrough key={route.params.join("/")} params={route.params} />}
        {active === "rfp" && <RfpAnswers projectId={route.params[0] ? Number(route.params[0]) : null} onOpen={(id) => (id === null ? navigate("rfp") : navigate("rfp", String(id)))} />}
        {active === "refine" && <Refine rfp={refine.rfp} report={refine.report} />}
        {active === "xbrl" && <XbrlFacts selectedRunId={route.params[0] ?? null} onSelectRun={(id) => navigate("xbrl", id)} />}
        {active === "library" && <DataLibrary />}
        {active === "companies" && <Company companyRef={route.params[0]} />}
        </Suspense>
      </main>
    </div>
  );
}

/** Opening ARP lands on the landing page; any other address opens the app as before. */
function Root() {
  const [landing, setLanding] = useState(() => entryTab(window.location.hash) === "welcome");
  useEffect(() => {
    const onHash = () => setLanding(entryTab(window.location.hash) === "welcome");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return landing ? <Landing /> : <App />;
}

export default Root;
