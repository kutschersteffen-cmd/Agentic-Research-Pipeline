import { useCallback, useEffect, useReducer, useState } from "react";
import { api } from "../api/client";
import type { RunManifest, StewardshipFlow } from "../types";
import { ACTIVE_STATUSES, decisionRunType, waitingCount } from "../lib/runs";
import { listAllRuns, usePoll } from "../lib/poll";
import { PROCESSES, WORKSPACES, stepHref, workspaceOfProcess, type Process, type Step, type Workspace, type WorkspaceId } from "../lib/processes";
import { useMe } from "../lib/reviewer";
import { STATE_LABEL, cardView, failedProcesses, openCount, processState, stepActivity, stepState, stepStatusLine, type Activity } from "../lib/workspaceCard";
import { Drawing, WorkspaceDrawing } from "../components/WorkspaceDrawing";
import { cockpitDrawing } from "../lib/workspaceDrawing";
import { announce } from "../lib/announce";
import { previousMonth } from "../lib/holdings";

// The start page, the five workspace pages and the process bar. Workspaces and
// their processes live in lib/processes.ts; this file draws them and reads
// their live state from the runs list and the house stewardship flow.


/** Runs, refreshed every 3 s while one is live, every 15 s otherwise. Null
 * until the first answer: a count nobody received is unknown, never zero. */
export function useRuns() {
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


/** The house stewardship flow, loaded once: its stages carry StewardIQ's numbers. */
export function useHouseFlow() {
  const [flow, setFlow] = useState<StewardshipFlow | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.getStewardshipFlow("house").then(setFlow, (err: Error) => setError(err.message));
  }, []);
  return { flow, error };
}

/** Loads and the monthly run leave no run behind: their steps read the feed overview and the last monthly run.
 * Loaded once; null until both answer (or when one fails), which leaves those steps as they were: "No runs yet". */
function useActivity(): Activity | null {
  const [activity, setActivity] = useState<Activity | null>(null);
  useEffect(() => {
    Promise.all([api.listFeeds(), api.lastMonthlyRun()]).then(
      ([f, lastRun]) => setActivity({ feeds: f.feeds, lastRun }),
      () => undefined,
    );
  }, []);
  return activity;
}

/** A workspace as a card: a way into it. A drawing, its purpose, one square per process and one
 * status line naming what matters now; the label carries each process's state for screen readers. */
function WorkspaceCard({ w, runs, flow }: { w: Workspace; runs: RunManifest[] | null; flow: StewardshipFlow | null }) {
  const v = cardView(w, runs, flow, new Date());
  const { word, tone, detail } = v.status;
  const n = w.processes.length;
  return (
    <a className={`hub-card${tone === "wait" ? " hub-card-await" : ""}`} href={`#/${w.id}`} aria-label={v.label}>
      <span className="hub-card-fig">
        <span className="hub-card-cap">{`${n} ${n === 1 ? "process" : "processes"}`}</span>
        <WorkspaceDrawing id={w.id} accent={tone === "wait" ? "wait" : tone === "now" ? "now" : null} />
      </span>
      <span className="hub-card-body">
        <span className="hub-card-name">{w.short ?? w.name}</span>
        <span className="hub-card-purpose">{w.purpose}</span>
        <span className="hub-card-status">
          <span className="hub-marks" aria-hidden="true">
            {v.dots.map((d, i) => (
              <span key={i} className={`hub-mark hub-mark-${d}`} />
            ))}
          </span>
          <span>
            <span className={`hub-status-${tone}`}>{word}</span>
            {detail && <span className="hub-status-detail"> · {detail}</span>}
          </span>
        </span>
      </span>
    </a>
  );
}

const COCKPIT_SHAPES = cockpitDrawing();

export function StartPage() {
  const { runs, error, retry } = useRuns();
  const { flow } = useHouseFlow();
  const reviewer = useMe()?.name ?? "";
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const name = reviewer.trim();
  const known = runs !== null;

  return (
    <div className="page hub hub-start">
      <header className="hub-hero">
        <h1>
          <span className="hub-hero-greet">
            {greeting}
            {name ? `, ${name}` : ""}.
          </span>
        </h1>
      </header>
      {error && (
        <p className="error-text" role="alert">
          Runs could not be loaded: {error}. {known ? "Showing the last answer." : "Counts are unknown until the backend responds."}{" "}
          <button className="link-button" onClick={retry}>
            Retry
          </button>
        </p>
      )}
      <div className="hub-cards">
        {WORKSPACES.map((w) => (
          <WorkspaceCard key={w.id} w={w} runs={runs} flow={flow} />
        ))}
      </div>
      {/* Not a workspace card: one StewardIQ screen with its own way in, so the cards stay five workspaces. */}
      <a className="hub-entry" href="#/stewardiq/cockpit" aria-label="Cockpit, StewardIQ" aria-describedby="hub-entry-cockpit-purpose">
        <span className="hub-entry-fig">
          <Drawing shapes={COCKPIT_SHAPES} />
        </span>
        <span className="hub-card-body">
          <span className="hub-card-cap hub-entry-cap">StewardIQ</span>
          <span className="hub-card-name">Cockpit</span>
          <span className="hub-card-purpose" id="hub-entry-cockpit-purpose">Engagement coverage, upcoming meetings, control gaps, escalation and votes on one page.</span>
        </span>
      </a>
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
function ProcessFlow({ p, runs, flow, activity }: { p: Process; runs: RunManifest[] | null; flow: StewardshipFlow | null; activity: Activity | null }) {
  const state = runs ? processState(p, runs, flow, activity) : null;
  const steps = (
    <ol className="hub-flow">
      {p.steps.map((s, i) => (
        <StepCard key={`${s.tab}-${s.sub ?? ""}-${i}`} s={s} i={i} p={p} runs={runs} flow={flow} activity={activity} />
      ))}
    </ol>
  );
  return (
    <section className="hub-process" aria-labelledby={`process-${p.id}`}>
      <div className="section-heading">
        <h2 id={`process-${p.id}`}>{p.title}</h2>
        <span className="hub-process-meta">
          {state && (
            <span className="hub-process-state">
              <span className={`hub-dot hub-dot-${state}`} aria-hidden />
              {STATE_LABEL[state]}
            </span>
          )}
          <span className="chip">{p.cadence}</span>
        </span>
      </div>
      <p className="help-text">
        <strong>Done when:</strong> {p.outcome}
      </p>
      {p.run && <RunProcess p={p} />}
      {/* A process nobody has run is folded away so the ones with activity stand out; one click opens it. */}
      {state === "idle" ? (
        <details className="hub-process-fold">
          <summary>Show {p.steps.length} steps</summary>
          {steps}
        </details>
      ) : (
        steps
      )}
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
        <a className="button-link" href="#/argus/new" onClick={() => writeWalk({ id: p.id, step: 1 })}>
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

function StepCard({ s, i, p, runs, flow, activity }: { s: Step; i: number; p: Process; runs: RunManifest[] | null; flow: StewardshipFlow | null; activity: Activity | null }) {
  const state = stepState(s, runs, flow, activity);
  const mine = s.runTypes && runs ? runs.filter((r) => s.runTypes!.includes(decisionRunType(r))).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)) : null;
  const last = mine?.[0];
  const waiting = mine && !s.reviewedElsewhere ? mine.reduce((n, r) => n + waitingCount(r), 0) : 0;
  const stage = s.stage ? flow?.stages.find((x) => x.id === s.stage) : undefined;
  const decisions = openCount(stage);
  const line = stepStatusLine(state, waiting, decisions, last?.updated_at ?? stepActivity(s, activity)?.at ?? null);
  if (s.planned) {
    return (
      <li className="hub-flow-item">
        <div className="hub-step hub-step-planned">
          <span className="hub-step-head">
            <span className="hub-step-num">{i + 1}</span>
            <span className="hub-step-title">{s.label}</span>
            <span className="chip">Planned</span>
          </span>
          <span className="hub-step-about">{s.does}</span>
        </div>
      </li>
    );
  }
  return (
    <li className="hub-flow-item">
      <a className={`hub-step hub-step-${state}`} href={stepHref(s)} onClick={() => writeWalk({ id: p.id, step: i })}>
        <span className="hub-step-head">
          <span className="hub-step-num">{i + 1}</span>
          <span className="hub-step-title">
            {s.label}
            {s.optional && <span className="muted"> (optional)</span>}
          </span>
          <span className="hub-step-go" aria-hidden>→</span>
        </span>
        <span className={`hub-step-status hub-step-status-${line.tone}${line.tone === "wait" ? " hub-step-banner" : ""}`}>{line.text}</span>
        <span className="hub-step-about">{s.does}</span>
        {last && (
          <span className="hub-step-rows">
            <span>
              Last run<b>{last.status.replace(/_/g, " ")}</b>
            </span>
            <span>
              Updated<b>{new Date(last.updated_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</b>
            </span>
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
          <span className={s.carried ? "hub-step-handoff" : "hub-step-handoff manual"} title={s.carried ? undefined : "Not passed on automatically: type it into the next step."}>
            Passes on: {s.handsOn}
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
  const activity = useActivity();

  return (
    <div className="page hub">
      <h1>{w.name}</h1>
      <p className="help-text">
        {w.purpose} Open a step to work in its screen; a bar there shows the next step. A dashed <span className="hub-step-handoff-key">re-entered by hand</span> line means that output is typed into the next step, not passed on.
      </p>
      {error && <p className="error-text" role="alert">Runs could not be loaded: {error}. Step states are unknown until the backend responds.</p>}
      {usesFlow && flowError && <p className="error-text" role="alert">The stewardship flow could not be loaded: {flowError}. Stage numbers are unknown.</p>}
      {failedProcesses(w, runs, flow, activity).map((title) => (
        <p key={title} className="hub-failed-line">
          Last run failed: {title}. <a href="#/history">Open Run history →</a>
        </p>
      ))}
      {w.processes.map((p) => (
        <ProcessFlow key={p.id} p={p} runs={runs} flow={flow} activity={activity} />
      ))}
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
