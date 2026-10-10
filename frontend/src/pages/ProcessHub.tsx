import { useCallback, useEffect, useReducer, useState, type ReactElement } from "react";
import { api } from "../api/client";
import type { RunManifest, StewardshipFlow } from "../types";
import { ACTIVE_STATUSES, REVIEWABLE_RUN_TYPES, runTypeLabel, waitingCount } from "../lib/runs";
import { listAllRuns, usePoll } from "../lib/poll";
import { DECISION_STAGES, PROCESSES, WORKSPACES, stepHref, workspaceOfProcess, type Process, type Step, type Workspace, type WorkspaceId } from "../lib/processes";
import { openCount } from "./steward/common";
import { useMe } from "../lib/reviewer";
import { NeedsYou } from "../components/NeedsYou";
import { announce } from "../lib/announce";
import { previousMonth } from "../lib/holdings";

// The start page, the five workspace pages and the process bar. Workspaces and
// their processes live in lib/processes.ts; this file draws them and reads
// their live state from the runs list and the house stewardship flow.

// One icon family on a 48 grid: the same stroke everywhere, and exactly one
// element per icon in the highlight colour (.hub-ico .hi / .hi-fill).
const ICON = { width: 52, height: 52, viewBox: "0 0 48 48", fill: "none", stroke: "currentColor", strokeWidth: 2.5, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, className: "hub-ico", "aria-hidden": true };

const ICONS: Record<WorkspaceId, ReactElement> = {
  stewardiq: (
    <svg {...ICON}>
      <path d="M24 5 L39 10 V23 C39 32 32.5 39.5 24 43 C15.5 39.5 9 32 9 23 V10 Z" />
      <path className="hi" d="M16.5 24 L22 29.5 L31.5 19" />
    </svg>
  ),
  argus: (
    <svg {...ICON}>
      <path d="M11 5 H29 L37 13 V43 H11 Z" />
      <path d="M29 5 V13 H37 M16 20 H31 M16 34 H26" />
      <path className="hi" d="M16 27 H44 M40 23 L44 27 L40 31" />
    </svg>
  ),
  transitionIntel: (
    <svg {...ICON}>
      <circle cx="24" cy="24" r="18" />
      <path d="M6 24 H42 M24 6 C17 12 17 36 24 42 M24 6 C31 12 31 36 24 42" opacity="0.55" />
      <path className="hi" d="M12 32 L20 25 L26 29 L37 16" />
    </svg>
  ),
  rdLab: (
    <svg {...ICON}>
      <circle cx="24" cy="24" r="19" strokeDasharray="2 4" opacity="0.55" />
      <path d="M24 24 L12.5 14 M24 24 L35.5 14 M24 24 L24 36" />
      <circle cx="11" cy="12.5" r="3.5" />
      <circle cx="37" cy="12.5" r="3.5" />
      <circle cx="24" cy="39.5" r="3.5" />
      <circle className="hi-fill" cx="24" cy="24" r="5.5" />
    </svg>
  ),
  dataHub: (
    <svg {...ICON}>
      <ellipse cx="24" cy="10" rx="15" ry="5" />
      <path d="M9 10 V38 C9 41 15.7 43 24 43 C32.3 43 39 41 39 38 V10" />
      <path d="M9 19 C9 22 15.7 24 24 24 C32.3 24 39 22 39 19" />
      <path className="hi" d="M9 28.5 C9 31.5 15.7 33.5 24 33.5 C32.3 33.5 39 31.5 39 28.5" />
    </svg>
  ),
};

const WORKSPACE_OF_RUN_TYPE = new Map(WORKSPACES.flatMap((w) => w.runTypes.map((t) => [t, w] as const)));

/** Runs, refreshed every 3 s while one is live, every 15 s otherwise. Null
 * until the first answer: a count nobody received is unknown, never zero. */
function useRuns() {
  const [runs, setRuns] = useState<RunManifest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRuns(await listAllRuns());
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);
  usePoll(load, runs?.some((r) => ACTIVE_STATUSES.has(r.status)) ? 3000 : 15000);
  return { runs, error, retry: load };
}

/** Open decisions across the Steward Workflow stages the processes own: the
 * sidebar's Steward Workflow badge uses the same count so the two agree. */
export const stageDecisions = (flow: StewardshipFlow | null) => DECISION_STAGES.reduce((n, id) => n + openCount(flow?.stages.find((x) => x.id === id)), 0);

/** The house stewardship flow, loaded once: its stages carry StewardIQ's numbers. */
function useHouseFlow() {
  const [flow, setFlow] = useState<StewardshipFlow | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.getStewardshipFlow("house").then(setFlow, (err: Error) => setError(err.message));
  }, []);
  return { flow, error };
}

type StepState = "done" | "now" | "wait" | "failed" | "idle";
const DONE = new Set(["completed", "partially_completed"]);

function stepState(step: Step, runs: RunManifest[] | null, flow: StewardshipFlow | null): StepState {
  if (step.runTypes && runs) {
    const mine = runs.filter((r) => step.runTypes!.includes(r.run_type));
    // Waiting on a person outranks running: that is what the signal colour is for.
    if (!step.reviewedElsewhere && mine.some((r) => waitingCount(r) > 0)) return "wait";
    if (mine.some((r) => ACTIVE_STATUSES.has(r.status))) return "now";
    const latest = mine.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0];
    if (latest?.status === "failed") return "failed";
    if (mine.some((r) => DONE.has(r.status))) return "done";
  }
  if (step.stage && openCount(flow?.stages.find((s) => s.id === step.stage)) > 0) return "wait";
  return "idle";
}

const RANK: StepState[] = ["wait", "now", "failed", "done", "idle"];
/** A process's one state: the most urgent of its steps'. */
const processState = (p: Process, runs: RunManifest[] | null, flow: StewardshipFlow | null): StepState => {
  const states = p.steps.map((s) => stepState(s, runs, flow));
  return RANK.find((r) => states.includes(r)) ?? "idle";
};

/** The one line a workspace box leads with: what waits on a person first, then
 * failures, then what is running. */
function headline(w: Workspace, runs: RunManifest[] | null, flow: StewardshipFlow | null): { tone: string; text: string } {
  if (!runs) return { tone: "", text: "Status unknown" };
  const mine = runs.filter((r) => w.runTypes.includes(r.run_type));
  const stages = new Set(w.processes.flatMap((p) => p.steps.map((s) => s.stage).filter(Boolean)));
  const waiting = mine.reduce((n, r) => n + waitingCount(r), 0) + [...stages].reduce((n, id) => n + openCount(flow?.stages.find((x) => x.id === id)), 0);
  const failed = mine.filter((r) => r.status === "failed").length;
  const running = mine.filter((r) => ACTIVE_STATUSES.has(r.status)).length;
  if (waiting > 0) return { tone: "await", text: `${waiting} waiting on you${failed > 0 ? ` · ${failed} failed` : ""}` };
  if (failed > 0) return { tone: "failed", text: `${failed} failed` };
  if (running > 0) return { tone: "running", text: `${running} running` };
  return { tone: "", text: "Nothing waiting" };
}

/** Where a run row goes: its review, its ballot, or its process. */
function runHref(r: RunManifest): string {
  if (r.review_count > 0 && REVIEWABLE_RUN_TYPES.has(r.run_type)) return `#/review/${r.run_type}/${encodeURIComponent(r.run_id)}`;
  if (r.run_type === "proxy_voting") return `#/voting/${encodeURIComponent(r.run_id)}`;
  const w = WORKSPACE_OF_RUN_TYPE.get(r.run_type);
  return w ? `#/${w.id}` : "#/history";
}

const WEEK_MS = 7 * 24 * 3600 * 1000;
const isToday = (iso: string) => new Date(iso).toDateString() === new Date().toDateString();
const recent = (iso: string) => Date.now() - new Date(iso).getTime() < WEEK_MS;

function ago(iso: string): string {
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 60) return `${Math.max(min, 1)} min ago`;
  if (min < 48 * 60) return `${Math.round(min / 60)} h ago`;
  return `${Math.round(min / 1440)} days ago`;
}

const STATE_LABEL: Record<StepState, string> = { done: "has a finished run", now: "running", wait: "waiting on a person", failed: "last run failed", idle: "no activity yet" };

/** A workspace as a card: icon, purpose, one dot per process, and one line
 * naming the process that matters now. */
function WorkspaceCard({ w, runs, flow }: { w: Workspace; runs: RunManifest[] | null; flow: StewardshipFlow | null }) {
  const h = headline(w, runs, flow);
  const last = runs?.filter((r) => w.runTypes.includes(r.run_type)).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0];
  const states = w.processes.map((p) => processState(p, runs, flow));
  // The process named is the one a person should look at: a wait first, then running or failed.
  const firstWait = states.indexOf("wait");
  const at = firstWait >= 0 ? firstWait : states.findIndex((st) => st === "now" || st === "failed");
  const now = at >= 0 ? w.processes[at].title : !runs ? "" : last ? `Last run ${ago(last.updated_at)}` : "No runs yet";
  return (
    <a className={`hub-card${h.tone ? ` hub-card-${h.tone}` : ""}`} href={`#/${w.id}`} aria-label={`${w.name}: ${h.text}${now ? `. ${now}` : ""}`}>
      {ICONS[w.id]}
      <span className="hub-card-text">
        <span className="hub-card-name">{w.name}</span>
        <span className="hub-card-purpose">{w.purpose}</span>
      </span>
      <ol className="hub-dots">
        {w.processes.map((p, i) => (
          <li key={p.id} className={`hub-dot-${states[i]}`}>
            <span className="visually-hidden">
              {p.title}: {STATE_LABEL[states[i]]}
            </span>
          </li>
        ))}
      </ol>
      <span className="hub-card-now">{now}</span>
      <span className="hub-card-foot">
        <span className={`hub-card-state ${h.tone}`}>{h.text}</span>
        <span className="hub-card-go">Open →</span>
      </span>
    </a>
  );
}

/** The key to the step dots, shared by the start page and the overviews so
 * one state always reads the same. */
function StateLegend() {
  return (
    <p className="muted hub-legend">
      {(["done", "now", "wait", "failed", "idle"] as StepState[]).map((st) => (
        <span key={st}>
          <span className={`hub-dot hub-dot-${st}`} aria-hidden />
          {STATE_LABEL[st]}
        </span>
      ))}
    </p>
  );
}

export function StartPage() {
  const { runs, error, retry } = useRuns();
  const { flow } = useHouseFlow();
  const reviewer = useMe()?.name ?? "";
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const name = reviewer.trim();

  const known = runs !== null;
  const all = runs ?? [];
  const active = all.filter((r) => ACTIVE_STATUSES.has(r.status));
  const waitingRuns = all.filter((r) => waitingCount(r) > 0);
  // Same count the cards add up: waiting run items plus open stewardship decisions.
  const decisions = stageDecisions(flow);
  const waiting = waitingRuns.reduce((n, r) => n + waitingCount(r), 0) + decisions;
  const failed = all.filter((r) => r.status === "failed" && recent(r.updated_at));
  const today = all.filter((r) => DONE.has(r.status) && isToday(r.updated_at));
  // What waits on a person is listed in "Needs you" above; this row is what is running, then what failed.
  const rank = (r: RunManifest) => (ACTIVE_STATUSES.has(r.status) ? 0 : 1);
  const chips = [...new Set([...active, ...failed])].sort((a, b) => rank(a) - rank(b) || (a.updated_at < b.updated_at ? 1 : -1)).slice(0, 6);
  const n = (v: number) => (known ? v : "—");

  return (
    <div className="page hub hub-start">
      <header className="hub-hero">
        <h1>
          <span className="hub-hero-greet">
            {greeting}
            {name ? `, ${name}` : ""}.
          </span>
          <span>
            {!known ? (error ? "Runs could not be loaded." : "Loading runs…") : waiting > 0 ? waiting === 1 ? "1 decision waits on you." : `${waiting} decisions wait on you.` : "Nothing waits on you."}
          </span>
        </h1>
        <dl className="hub-stats">
          <div className={known && waiting > 0 ? "you" : undefined}>
            <dt>waiting on you</dt>
            <dd>{n(waiting)}</dd>
          </div>
          <div>
            <dt>running</dt>
            <dd>{n(active.length)}</dd>
          </div>
          <div className={known && failed.length > 0 ? "failed" : undefined}>
            <dt>failed this week</dt>
            <dd>{n(failed.length)}</dd>
          </div>
          <div>
            <dt>done today</dt>
            <dd>{n(today.length)}</dd>
          </div>
        </dl>
      </header>
      {error && (
        <p className="error-text" role="alert">
          Runs could not be loaded: {error}. {known ? "Showing the last answer." : "Counts are unknown until the backend responds."}{" "}
          <button className="link-button" onClick={retry}>
            Retry
          </button>
        </p>
      )}
      <NeedsYou runs={runs} flow={flow} />
      <div className="hub-cards">
        {WORKSPACES.map((w) => (
          <WorkspaceCard key={w.id} w={w} runs={runs} flow={flow} />
        ))}
      </div>
      <StateLegend />
      <nav className="hub-now" aria-label="Runs running or failed">
        <span className="hub-now-label">Now</span>
        {chips.map((r) => {
          const state = ACTIVE_STATUSES.has(r.status) ? "now" : "failed";
          const pct = r.company_count > 0 ? Math.round((r.completed_count / r.company_count) * 100) : 0;
          return (
            <a key={r.run_id} className={`hub-chip hub-chip-${state}`} href={runHref(r)}>
              <span className={`hub-dot hub-dot-${state}`} aria-hidden />
              {runTypeLabel(r.run_type)} <span className="hub-chip-id">{r.run_id}</span> · {state === "now" ? `running ${pct}%` : "failed"}
            </a>
          );
        })}
        {known && chips.length === 0 && <span className="muted">Nothing running or failed.</span>}
        <a className="hub-now-all" href="#/history">
          All runs →
        </a>
      </nav>
    </div>
  );
}

// The process a person is walking through, remembered for this browser tab
// only, so a step's screen can show where it sits and what comes next.
const WALK_KEY = "arp.processWalk";
type Walk = { id: string; step: number };

function readWalk(): Walk | null {
  try {
    return JSON.parse(sessionStorage.getItem(WALK_KEY) ?? "null");
  } catch {
    return null;
  }
}

function writeWalk(walk: Walk | null) {
  try {
    if (walk) sessionStorage.setItem(WALK_KEY, JSON.stringify(walk));
    else sessionStorage.removeItem(WALK_KEY);
  } catch {
    /* storage unavailable: the bar just won't show */
  }
}

/** One process drawn as its steps in order: each card carries the step's live
 * state, what it hands on, and opens the screen that does it. */
function ProcessFlow({ p, runs, flow }: { p: Process; runs: RunManifest[] | null; flow: StewardshipFlow | null }) {
  return (
    <section className="hub-process" aria-labelledby={`process-${p.id}`}>
      <div className="section-heading">
        <h2 id={`process-${p.id}`}>{p.title}</h2>
        <span className="chip">{p.cadence}</span>
      </div>
      <p className="help-text">
        <strong>Done when:</strong> {p.outcome}
      </p>
      {p.run && <RunProcess p={p} />}
      <ol className="hub-flow">
        {p.steps.map((s, i) => (
          <StepCard key={`${s.tab}-${s.sub ?? ""}-${i}`} s={s} i={i} p={p} runs={runs} flow={flow} />
        ))}
      </ol>
    </section>
  );
}

type MonthResult = Awaited<ReturnType<typeof api.runMonth>>;

/** End to end where an engine exists. It never skips a person: Extraction stops wherever something is flagged, and a
 * blocked month says what it is missing. */
function RunProcess({ p }: { p: Process }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<(MonthResult & { month: string }) | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (p.run === "extraction") {
    return (
      <p className="hub-run">
        <a className="button-link" href="#/extraction/companies/auto" onClick={() => writeWalk({ id: p.id, step: 1 })}>
          Run process
        </a>{" "}
        <span className="muted">Pick the companies; Identify, Documents and Extract then follow on their own and stop wherever something is flagged.</span>
      </p>
    );
  }

  async function runMonth() {
    const month = previousMonth(new Date());
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.runMonth(month);
      setResult({ ...r, month });
      announce(r.status === "ran" ? `Month ${month} ran` : `Month ${month} is blocked`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="hub-run">
      <button onClick={() => void runMonth()} disabled={running}>{running ? "Running…" : "Run process"}</button>{" "}
      <span className="muted">Runs last month: alerts from the loaded holdings, ESG data and news, then stewardship triggers.</span>
      {error && <p className="error-text" role="alert">{error}</p>}
      {result?.status === "ran" && (
        <p role="status">
          {result.month} ran: {result.alerts} new alerts, {result.triggers} triggers. <a href="#/portfolio-monitoring/monitoring">Open alerts →</a>
        </p>
      )}
      {result?.status === "blocked" && (
        <div role="status">
          <p>{result.month} is blocked:</p>
          <ul>{result.blocked_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          <a href="#/portfolio-monitoring/holdings">Load what is missing in Holdings Intake →</a>
        </div>
      )}
    </div>
  );
}

function StepCard({ s, i, p, runs, flow }: { s: Step; i: number; p: Process; runs: RunManifest[] | null; flow: StewardshipFlow | null }) {
  const state = stepState(s, runs, flow);
  const mine = s.runTypes && runs ? runs.filter((r) => s.runTypes!.includes(r.run_type)).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)) : null;
  const last = mine?.[0];
  const waiting = mine && !s.reviewedElsewhere ? mine.reduce((n, r) => n + waitingCount(r), 0) : 0;
  const stage = s.stage ? flow?.stages.find((x) => x.id === s.stage) : undefined;
  const decisions = openCount(stage);
  return (
    <li className="hub-flow-item">
      <a className={`hub-step hub-step-${state}`} href={stepHref(s)} onClick={() => writeWalk({ id: p.id, step: i })}>
        <span className="hub-step-head">
          <span className="hub-step-num">{i + 1}</span>
          <span className="hub-step-title">
            {s.label}
            {s.optional && <span className="muted"> (optional)</span>}
          </span>
        </span>
        {(waiting > 0 || decisions > 0) && (
          <span className="hub-step-banner">{waiting > 0 ? `${waiting} waiting on you` : `${decisions} decision${decisions === 1 ? "" : "s"} open`}</span>
        )}
        <span className="hub-step-about">{s.does}</span>
        {mine && (
          <span className="hub-step-rows">
            <span>
              Last run<b>{last ? last.status.replace(/_/g, " ") : "none yet"}</b>
            </span>
            {last && (
              <span>
                Updated<b>{new Date(last.updated_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</b>
              </span>
            )}
          </span>
        )}
        {stage && stage.metrics.length > 0 && (
          <span className="hub-step-rows">
            {/* The same three the Steward Workflow stage card shows, so the
                number behind the "decisions open" banner is on screen. */}
            {stage.metrics.slice(0, 3).map((m) => (
              <span key={m.label}>
                {m.label}
                <b>{m.value}</b>
              </span>
            ))}
          </span>
        )}
        {s.handsOn && i < p.steps.length - 1 && (
          <span className={s.carried ? "hub-step-handoff" : "hub-step-handoff manual"}>
            Hands on: {s.handsOn}
            {!s.carried && " · re-entered by hand"}
          </span>
        )}
      </a>
    </li>
  );
}

/** A workspace: its processes, each drawn step by step, then every screen it
 * owns so a single step can be run by hand. */
export function WorkspaceOverview({ id }: { id: WorkspaceId }) {
  const w = WORKSPACES.find((x) => x.id === id)!;
  const { runs, error } = useRuns();
  const { flow, error: flowError } = useHouseFlow();
  const usesFlow = w.processes.some((p) => p.steps.some((s) => s.stage));

  return (
    <div className="page hub">
      <p className="hub-crumb">
        <a href="#/home">Start</a> › {w.name}
      </p>
      <h1>{w.name}</h1>
      <p className="help-text">{w.purpose} Open a step to work in its screen; a bar there shows the next step.</p>
      {error && <p className="error-text" role="alert">Runs could not be loaded: {error}. Step states are unknown until the backend responds.</p>}
      {usesFlow && flowError && <p className="error-text" role="alert">The stewardship flow could not be loaded: {flowError}. Stage numbers are unknown.</p>}
      {w.processes.map((p) => (
        <ProcessFlow key={p.id} p={p} runs={runs} flow={flow} />
      ))}
      <StateLegend />
      <nav className="hub-screens" aria-label={`${w.name} screens`}>
        <span className="hub-now-label">Screens</span>
        {w.screens.map(([href, label]) => (
          <a key={href} className="hub-chip" href={href}>
            {label}
          </a>
        ))}
      </nav>
    </div>
  );
}

/** "Step 2 of 5" above a screen reached from a process, with the next step
 * one click away. Shows only while the current screen is a step of that
 * process, so wandering off hides it and coming back restores it. */
export function ProcessBar({ tab, sub }: { tab: string; sub?: string }) {
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  const walk = readWalk();
  const process = PROCESSES.find((p) => p.id === walk?.id);
  if (!walk || !process) return null;
  const matches = (s: Step) => s.tab === tab && (!s.sub || !sub || s.sub === sub);
  const i = process.steps[walk.step] && matches(process.steps[walk.step]) ? walk.step : process.steps.findIndex(matches);
  if (i < 0) return null;
  const next = process.steps[i + 1];
  const w = workspaceOfProcess(process.id)!;
  return (
    <nav className="process-bar" aria-label="Process progress">
      <a href={`#/${w.id}`} className="process-bar-title">
        {w.name} · {process.title}
      </a>
      <span>
        Step {i + 1} of {process.steps.length}: <strong>{process.steps[i].label}</strong>
      </span>
      {next ? (
        <a href={stepHref(next)} className="process-bar-next" onClick={() => writeWalk({ id: process.id, step: i + 1 })}>
          Next: {next.label} →
        </a>
      ) : (
        <span className="muted">Last step</span>
      )}
      <button
        className="link-button"
        aria-label="Stop following this process"
        onClick={() => {
          writeWalk(null);
          rerender();
        }}
      >
        ✕
      </button>
    </nav>
  );
}
