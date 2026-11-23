import { useCallback, useEffect, useReducer, useState } from "react";
import { api } from "../api/client";
import type { RunManifest, StewardshipFlow, StewardshipStage } from "../types";
import { ACTIVE_STATUSES, REVIEWABLE_RUN_TYPES, decisionRunType, waitingCount } from "../lib/runs";
import { listAllRuns, usePoll } from "../lib/poll";
import { PROCESSES, WORKSPACES, stepHref, workspaceOfProcess, type Process, type Step, type Workspace, type WorkspaceId } from "../lib/processes";
import { useMe } from "../lib/reviewer";
import { STATE_LABEL, askBox, cardView, heroCaption, needsYouText, runningDetail, workingSentence, workspaceCaption, failedProcesses, flowTrack, openCount, processState, stepActivity, stepCount, stepRail, stepState, stepStatusLine, type Activity, type StepState } from "../lib/workspaceCard";
import { Drawing, WorkspaceDrawing } from "../components/WorkspaceDrawing";
import { Orb } from "../components/Orb";
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
export function useActivity(): Activity | null {
  const [activity, setActivity] = useState<Activity | null>(null);
  useEffect(() => {
    Promise.all([api.listFeeds(), api.lastMonthlyRun()]).then(
      ([f, lastRun]) => setActivity({ feeds: f.feeds, lastRun }),
      () => undefined,
    );
  }, []);
  return activity;
}

/** A workspace as a card: a way into it. A drawing whose status part lights up, its purpose, a rail with one
 * segment per process and one status line naming what matters now; the label carries each process's state for
 * screen readers. */
function WorkspaceCard({ w, runs, flow, known }: { w: Workspace; runs: RunManifest[] | null; flow: StewardshipFlow | null; known: boolean }) {
  const v = cardView(w, runs, flow, new Date());
  const { word, tone } = v.status;
  // Running: name the step and where it sits; every other detail stays as cardStatus() gives it.
  const detail = (tone === "now" && runningDetail(w, runs, flow)) || v.status.detail;
  const n = w.processes.length;
  const lit = tone === "wait" ? "wait" : tone === "now" ? "now" : null;
  return (
    <a className={`hub-card${tone === "wait" ? " hub-card-await" : tone === "now" ? " hub-card-run" : ""}`} href={`#/${w.id}`} aria-label={v.label}>
      <span className="hub-card-fig">
        <span className="hub-card-cap">{`${n} ${n === 1 ? "process" : "processes"}`}</span>
        <WorkspaceDrawing id={w.id} accent={lit} known={known} />
      </span>
      <span className="hub-card-body">
        <span className="hub-card-name">{w.name}</span>
        <span className="hub-card-purpose">{w.purpose}</span>
        <span className="hub-card-status">
          <span className="hub-card-line">
            <span className={`hub-status-${tone}`}>{word}</span>
            {detail && <span className="hub-status-detail">{detail}</span>}
          </span>
          <span className="hub-rail" data-rail aria-hidden="true">
            {v.dots.map((d, i) => (
              <span key={i} data-seg={d} />
            ))}
          </span>
        </span>
      </span>
    </a>
  );
}

/** `GET /api/waiting`'s total, loaded once; null until it answers or when it fails. */
function useWaitingTotal() {
  const [total, setTotal] = useState<number | null>(null);
  useEffect(() => {
    api.getWaiting().then((w) => setTotal(w.total), () => setTotal(null));
  }, []);
  return total;
}

const COCKPIT_SHAPES = cockpitDrawing();

export function StartPage() {
  const { runs, error, retry } = useRuns();
  const { flow, error: flowError } = useHouseFlow();
  // A drawing's first known status is drawn in place. A workspace that reads the stewardship flow waits for it
  // too, so its answer arriving after the runs does not read as a change.
  const flowSettled = flow !== null || flowError !== null;
  const drawnKnown = (w: Workspace) => runs !== null && (flowSettled || !w.processes.some((p) => p.steps.some((s) => s.stage)));
  const reviewer = useMe()?.name ?? "";
  const [opened] = useState(() => new Date());
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const name = reviewer.trim();
  const known = runs !== null;
  const waiting = useWaitingTotal();
  // Unknown counts are left out, never shown as zero.
  const working = known && !error ? workingSentence(runs) : null;
  const needs = needsYouText(waiting);

  return (
    <div className="page hub hub-start">
      <header className="hub-hero">
        <div className="hub-hero-copy">
          <p className="hub-hero-cap">{heroCaption(opened)}</p>
          <h1>
            {greeting}
            {name ? `, ${name}` : ""}.
          </h1>
          <p className="hub-hero-lead" data-hero-lead>
            {working}
            {working && needs ? " " : ""}
            {needs && <a href="#/review">{needs}</a>}
          </p>
        </div>
        <div className="hub-hero-stage">
          <Orb place="start" label />
        </div>
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
          <WorkspaceCard key={w.id} w={w} runs={runs} flow={flow} known={drawnKnown(w)} />
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
 * state and what it hands on; a click opens its details panel under the flow. */
export function ProcessFlow({ p, runs, flow, activity, foldable = true }: { p: Process; runs: RunManifest[] | null; flow: StewardshipFlow | null; activity: Activity | null; foldable?: boolean }) {
  const state = runs ? processState(p, runs, flow, activity) : null;
  const [open, setOpen] = useState<number | null>(null);
  // While a panel is open the flow keeps the fold it had when the panel opened, so a poll never folds it away under the reader.
  const [openFolded, setOpenFolded] = useState(false);
  const folded = foldable && (open !== null ? openFolded : state === "idle");
  const toggle = (i: number) => {
    setOpenFolded(folded);
    setOpen(open === i ? null : i);
  };
  const views = p.steps.map((s) => stepView(s, runs, flow, activity));
  const { reached, runInto } = flowTrack(views.map((v) => v.state));
  const rail = stepRail(p, runs, flow, activity);
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "Escape" || open === null) return;
    e.stopPropagation(); // Esc closes this panel only, not the Ask ARP panel listening on window
    setOpen(null);
    document.getElementById(`step-${p.id}-${open}`)?.focus();
  };
  const steps = (
    <div onKeyDown={onKeyDown}>
      {/* One segment per step (DESIGN.md, Status Rail); inside the fold, so a folded process shows none. */}
      <span className="hub-rail hub-step-rail" data-rail aria-hidden="true">
        {rail.map((seg, i) => (
          <span key={i} data-seg={seg} />
        ))}
      </span>
      <ol className="hub-flow">
        {p.steps.map((s, i) => (
          <li key={`${s.tab}-${s.sub ?? ""}-${i}`} className={`hub-flow-item${i <= reached ? " reached" : ""}${runInto[i] ? " run-into" : ""}`}>
            <StepCard s={s} i={i} p={p} view={views[i]} count={views[i].state === "now" ? stepCount(s, runs) : null} open={open === i} onToggle={() => toggle(i)} />
          </li>
        ))}
      </ol>
      {open !== null && <StepPanel s={p.steps[open]} i={open} p={p} view={views[open]} />}
    </div>
  );
  return (
    <section className="hub-process" data-state={state ?? "unknown"} aria-labelledby={`process-${p.id}`}>
      <div className="section-heading">
        <h2 id={`process-${p.id}`}>{p.title}</h2>
        <span className="hub-process-meta">
          {state && (
            <span className="hub-process-state">
              <span className={`hub-mark hub-mark-${state}`} aria-hidden />
              <span className={`hub-status-${state}`}>{STATE_LABEL[state]}</span>
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
      {folded ? (
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

type StepView = { state: StepState; line: ReturnType<typeof stepStatusLine>; last: RunManifest | undefined; stage: StewardshipStage | undefined; fromRuns: boolean };

/** What a step shows, worked out once for its card and its details panel. */
function stepView(s: Step, runs: RunManifest[] | null, flow: StewardshipFlow | null, activity: Activity | null): StepView {
  const state = stepState(s, runs, flow, activity);
  const mine = s.runTypes && runs ? runs.filter((r) => s.runTypes!.includes(decisionRunType(r))).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)) : null;
  const last = mine?.[0];
  const waiting = mine && !s.reviewedElsewhere ? mine.reduce((n, r) => n + waitingCount(r), 0) : 0;
  const stage = s.stage ? flow?.stages.find((x) => x.id === s.stage) : undefined;
  const line = stepStatusLine(state, waiting, openCount(stage), last?.updated_at ?? stepActivity(s, activity)?.at ?? null);
  return { state, line, last, stage, fromRuns: waiting > 0 };
}

function StepCard({ s, i, p, view, count, open, onToggle }: { s: Step; i: number; p: Process; view: StepView; count: string | null; open: boolean; onToggle: () => void }) {
  const { state, line, last, stage } = view;
  if (s.planned) {
    return (
      <div className="hub-step hub-step-planned">
        <span className="hub-step-head">
          <span className="hub-step-num">{i + 1}</span>
          <span className="hub-step-title">{s.label}</span>
          <span className="chip">Planned</span>
        </span>
        <span className="hub-step-about">{s.does}</span>
      </div>
    );
  }
  return (
    <button type="button" id={`step-${p.id}-${i}`} className={`hub-step hub-step-${state}`} aria-expanded={open} aria-controls={`step-panel-${p.id}`} onClick={onToggle}>
      <span className="hub-step-head">
        <span className="hub-step-num">{i + 1}</span>
        <span className="hub-step-title">
          {s.label}
          {s.optional && <span className="muted"> (optional)</span>}
        </span>
      </span>
      {count && <span className="hub-step-count">{count}</span>}
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
    </button>
  );
}

/** The open step's details, under its process's flow. Only its "Open" link leaves the page. */
function StepPanel({ s, i, p, view }: { s: Step; i: number; p: Process; view: StepView }) {
  const { state, line, last, fromRuns } = view;
  // Run counts the Review Queue holds go there; decisions and other runs are worked in the step's own screen.
  const nowHref = fromRuns && s.runTypes!.every((t) => REVIEWABLE_RUN_TYPES.has(t)) ? "#/review" : stepHref(s);
  return (
    <div className="hub-step-panel" role="region" id={`step-panel-${p.id}`} aria-label={`${s.label} details`}>
      <p className="meta">
        Step {i + 1} of {p.steps.length}
      </p>
      <h3>{s.label}</h3>
      <p>{s.does}</p>
      <dl>
        <dt>Status</dt>
        <dd>
          <span className={`hub-mark hub-mark-${state}`} aria-hidden />
          {STATE_LABEL[state]}
        </dd>
        <dt>Now</dt>
        <dd>{line.tone === "wait" ? <a href={nowHref}>{line.text}</a> : line.text}</dd>
        {last && (
          <>
            <dt>Latest run</dt>
            <dd>
              <code>{last.run_id}</code> · {last.status.replace(/_/g, " ")}
            </dd>
          </>
        )}
      </dl>
      <a className="button-link" href={stepHref(s)} onClick={() => writeWalk({ id: p.id, step: i })}>
        Open {s.label} →
      </a>
    </div>
  );
}

/** The one legend line under the flows. */
export const HandoffLegend = () => (
  <p className="muted">
    <span className="hub-step-handoff-key">Dashed line</span>: typed in by hand, not passed on.
  </p>
);

/** A workspace: a header (caption, pixel title, purpose, status line, the drawing in its figure box), an Ask ARP card
 * with the Orb for those who may ask, then its processes as panels, each drawn step by step. */
export function WorkspaceOverview({ id, onAsk }: { id: WorkspaceId; onAsk?: (question: string) => void }) {
  const w = WORKSPACES.find((x) => x.id === id)!;
  const { runs, error } = useRuns();
  const { flow, error: flowError } = useHouseFlow();
  const usesFlow = w.processes.some((p) => p.steps.some((s) => s.stage));
  const activity = useActivity();
  // The header lights up like the workspace's start-page card: waiting, running, or not at all.
  const { word, tone, detail } = cardView(w, runs, flow, new Date()).status;
  const shown = (tone === "now" && runningDetail(w, runs, flow, true)) || detail;
  const lit = tone === "wait" ? "wait" : tone === "now" ? "now" : null;
  const ask = askBox(w, onAsk !== undefined);

  return (
    <div className={`page hub hub-ws${ask ? " hub-ws-ask" : ""}`}>
      <p className="hub-ws-cap">{workspaceCaption(w)}</p>
      <h1>{w.name}</h1>
      <p className="help-text">{w.purpose}</p>
      <p className="hub-ws-status" data-ws-status>
        <span className={`hub-mark hub-mark-${tone}`} aria-hidden />
        <span className={`hub-status-${tone}`}>{word}</span> {shown && <span className="hub-status-detail">{shown}</span>}
      </p>
      <div className="hub-ws-fig" data-tone={lit ?? "none"}>
        <WorkspaceDrawing id={w.id} accent={lit} known={runs !== null && (flow !== null || flowError !== null)} />
      </div>
      {ask && <WorkspaceAsk label={ask.label} onAsk={onAsk!} />}
      <div className="hub-ws-body">
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
        <HandoffLegend />
      </div>
    </div>
  );
}

/** Ask ARP inside a workspace: the Orb and one question box. Enter sends the trimmed question, as typed, as a new ask
 * thread on the Agent screen; an empty box sends nothing. */
function WorkspaceAsk({ label, onAsk }: { label: string; onAsk: (question: string) => void }) {
  const [text, setText] = useState("");
  return (
    <aside className="hub-ask" aria-label="Ask ARP">
      <div className="hub-ask-stage">
        <span className="hub-ask-cap" aria-hidden="true">Ask ARP</span>
        <Orb place="workspace" label />
      </div>
      <form
        className="hub-ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          const q = text.trim();
          if (q) onAsk(q);
        }}
      >
        <input type="text" aria-label={label} placeholder={label} value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" enterKeyHint="send" />
      </form>
    </aside>
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
