import { useCallback, useEffect, useState, type ReactElement } from "react";
import { api } from "../api/client";
import type { RunManifest, StewardshipFlow } from "../types";
import { ACTIVE_STATUSES, REVIEWABLE_RUN_TYPES, runTypeLabel, waitingCount } from "../lib/runs";
import { openCount } from "./steward/common";
import { useReviewer } from "../lib/reviewer";

// The start page and the three process overview pages. A process is a named
// group of screens in order; each step links to the screen that does it and
// reads its live state from the runs list (or, for StewardIQ, the house
// stewardship flow). Data Engineer has no overview page: its box opens
// Extraction, which already draws its own pipeline.
type Step = { label: string; screen: string; href: string; about: string; runTypes?: string[]; stage?: string };
type Process = { id: string; name: string; purpose: string; href: string; runTypes: string[]; steps: Step[]; icon: ReactElement };

// One icon family on a 48 grid: the same stroke everywhere, and exactly one
// element per icon in the highlight colour (.hub-ico .hi / .hi-fill).
const ICON = { width: 52, height: 52, viewBox: "0 0 48 48", fill: "none", stroke: "currentColor", strokeWidth: 2.5, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, className: "hub-ico", "aria-hidden": true };

const PROCESSES: Process[] = [
  {
    id: "stewardiq",
    name: "StewardIQ",
    purpose: "Engage companies, vote, and track what they commit to.",
    href: "#/stewardiq",
    runTypes: ["proxy_voting"],
    icon: (
      <svg {...ICON}>
        <path d="M24 5 L39 10 V23 C39 32 32.5 39.5 24 43 C15.5 39.5 9 32 9 23 V10 Z" />
        <path className="hi" d="M16.5 24 L22 29.5 L31.5 19" />
      </svg>
    ),
    steps: [
      { label: "Monitor", screen: "Steward · Monitoring", href: "#/stewardship/monitoring", stage: "monitoring", about: "Triggers on holdings, checked against house policy." },
      { label: "Select", screen: "Steward · Selection", href: "#/stewardship/selection", stage: "selection", about: "Which companies the program engages this cycle." },
      { label: "Engage", screen: "Steward · Drafting", href: "#/stewardship/drafting", stage: "drafting", about: "Dossier, outreach letter and talking points." },
      { label: "Vote", screen: "Proxy Voting", href: "#/voting", runTypes: ["proxy_voting"], about: "Ballots drafted by the policy, decided by a person." },
      { label: "Checkpoint", screen: "Steward · Checkpoint", href: "#/stewardship/checkpoint", stage: "checkpoint", about: "Votes decided against the policy, with their reason." },
      { label: "Track", screen: "Steward · Tracking", href: "#/stewardship/tracking", stage: "tracking", about: "Commitments verified or missed; missed ones escalate." },
    ],
  },
  {
    id: "themeMachine",
    name: "Theme Machine",
    purpose: "Spot emerging themes and match companies to them.",
    href: "#/themeMachine",
    runTypes: ["emerging_themes", "taxonomy_research", "theme"],
    icon: (
      <svg {...ICON}>
        <circle cx="24" cy="24" r="19" strokeDasharray="2 4" opacity="0.55" />
        <path d="M24 24 L12.5 14 M24 24 L35.5 14 M24 24 L24 36" />
        <circle cx="11" cy="12.5" r="3.5" />
        <circle cx="37" cy="12.5" r="3.5" />
        <circle cx="24" cy="39.5" r="3.5" />
        <circle className="hi-fill" cx="24" cy="24" r="5.5" />
      </svg>
    ),
    steps: [
      { label: "Spot", screen: "Emerging Themes", href: "#/emergingThemes", runTypes: ["emerging_themes"], about: "Candidate themes from filings and news." },
      { label: "Define", screen: "Taxonomy Library", href: "#/taxonomy", runTypes: ["taxonomy_research"], about: "The theme's activities; ratify a version." },
      { label: "Match", screen: "Thematic Universe", href: "#/theme", runTypes: ["theme"], about: "Companies matched to activities, with cited rationale." },
      { label: "Review", screen: "Review Queue", href: "#/review", runTypes: ["theme"], about: "Resolve contested classifications." },
    ],
  },
  {
    id: "dataEngineer",
    name: "Data Engineer",
    purpose: "Extract data points from disclosures, each cited to its source.",
    href: "#/extraction",
    runTypes: ["extraction", "financials", "tnfd", "transition_plan"],
    icon: (
      <svg {...ICON}>
        <path d="M11 5 H29 L37 13 V43 H11 Z" />
        <path d="M29 5 V13 H37 M16 20 H31 M16 34 H26" />
        <path className="hi" d="M16 27 H44 M40 23 L44 27 L40 31" />
      </svg>
    ),
    // One per Extraction profile; only drawn as the box's progress strip.
    steps: [
      { label: "Custom schema", screen: "Extraction", href: "#/extraction", runTypes: ["extraction"], about: "" },
      { label: "Financials", screen: "Extraction", href: "#/extraction", runTypes: ["financials"], about: "" },
      { label: "TNFD", screen: "Extraction", href: "#/extraction", runTypes: ["tnfd"], about: "" },
      { label: "Transition plan", screen: "Extraction", href: "#/transitionPlan", runTypes: ["transition_plan"], about: "" },
    ],
  },
  {
    id: "designStudio",
    name: "Design Studio",
    purpose: "Ratify scoring templates, then build the index.",
    href: "#/designStudio",
    runTypes: ["calibration"],
    icon: (
      <svg {...ICON}>
        <path d="M6 42 H42 M11 42 V30 H17 V42 M21 42 V21 H27 V42" />
        <path className="hi-fill" d="M31 42 V12 H37 V42 Z" />
        <path d="M5 12 H28" strokeDasharray="2 3" opacity="0.6" />
      </svg>
    ),
    steps: [
      { label: "Build template", screen: "Decision Studio", href: "#/decision", about: "Load a table or a finished run; set indicators, gates and tiers." },
      { label: "Ratify & publish", screen: "Decision Studio", href: "#/decision", about: "A named person ratifies the template, then the tiers are published." },
      { label: "Construct index", screen: "Index Construction", href: "#/index", about: "Screen, select, weight and cap from the published scores." },
      { label: "Calibrate", screen: "Index Construction", href: "#/index", runTypes: ["calibration"], about: "Save an effective-dated calibration." },
    ],
  },
];

const PROCESS_OF_RUN_TYPE = new Map(PROCESSES.flatMap((p) => p.runTypes.map((t) => [t, p] as const)));

/** Runs, refreshed every 3 s. Null until the first answer: a count nobody
 * received is unknown, never zero. */
function useRuns() {
  const [runs, setRuns] = useState<RunManifest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRuns(((await api.listRuns()) as { runs: RunManifest[] }).runs);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const tick = async () => {
      await load();
      if (!cancelled) timer = window.setTimeout(tick, 3000);
    };
    tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [load]);
  return { runs, error, retry: load };
}

/** The house stewardship flow, loaded once: its stages carry StewardIQ's numbers. */
/** Open decisions across the StewardIQ stages the start page shows: the
 * sidebar's Steward Workflow badge uses the same count so the two agree. */
export const stageDecisions = (flow: StewardshipFlow | null) =>
  PROCESSES.flatMap((p) => p.steps).reduce((n, s) => n + (s.stage ? openCount(flow?.stages.find((x) => x.id === s.stage)) : 0), 0);

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
    if (mine.some((r) => ACTIVE_STATUSES.has(r.status))) return "now";
    if (mine.some((r) => waitingCount(r) > 0)) return "wait";
    const latest = mine.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0];
    if (latest?.status === "failed") return "failed";
    if (mine.some((r) => DONE.has(r.status))) return "done";
  }
  if (step.stage && openCount(flow?.stages.find((s) => s.id === step.stage)) > 0) return "wait";
  return "idle";
}

/** The one line a process box leads with: what waits on a person first, then
 * failures, then what is running. */
function headline(p: Process, runs: RunManifest[] | null, flow: StewardshipFlow | null): { tone: string; text: string } {
  if (!runs) return { tone: "", text: "Status unknown" };
  const mine = runs.filter((r) => p.runTypes.includes(r.run_type));
  const waiting = mine.reduce((n, r) => n + waitingCount(r), 0) + p.steps.reduce((n, s) => n + (s.stage ? openCount(flow?.stages.find((x) => x.id === s.stage)) : 0), 0);
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
  return PROCESS_OF_RUN_TYPE.get(r.run_type)?.href ?? "#/history";
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

/** A process as a card: icon, purpose, its steps as a row of dots, and one
 * line naming the step that matters now. */
function ProcessCard({ p, runs, flow }: { p: Process; runs: RunManifest[] | null; flow: StewardshipFlow | null }) {
  const h = headline(p, runs, flow);
  const last = runs?.filter((r) => p.runTypes.includes(r.run_type)).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0];
  const states = p.steps.map((s) => stepState(s, runs, flow));
  const at = states.findIndex((st) => st === "wait" || st === "now" || st === "failed");
  const now = at >= 0 ? `Step ${at + 1} of ${p.steps.length} · ${p.steps[at].label}` : !runs ? "" : last ? `Last run ${ago(last.updated_at)}` : "No runs yet";
  return (
    <a className={`hub-card${h.tone ? ` hub-card-${h.tone}` : ""}`} href={p.href} aria-label={`${p.name}: ${h.text}${now ? `. ${now}` : ""}`}>
      {p.icon}
      <span className="hub-card-text">
        <span className="hub-card-name">{p.name}</span>
        <span className="hub-card-purpose">{p.purpose}</span>
      </span>
      <ol className="hub-dots">
        {p.steps.map((s, i) => (
          <li key={s.label} className={`hub-dot-${states[i]}`}>
            <span className="visually-hidden">
              {s.label}: {STATE_LABEL[states[i]]}
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
  const [reviewer] = useReviewer();
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
  // Waiting on a person first, then running, then failed: the order of what to do.
  const rank = (r: RunManifest) => (waitingCount(r) > 0 && !ACTIVE_STATUSES.has(r.status) ? 0 : ACTIVE_STATUSES.has(r.status) ? 1 : 2);
  const chips = [...new Set([...waitingRuns, ...active, ...failed])].sort((a, b) => rank(a) - rank(b) || (a.updated_at < b.updated_at ? 1 : -1)).slice(0, 6);
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
      <div className="hub-cards">
        {PROCESSES.map((p) => (
          <ProcessCard key={p.id} p={p} runs={runs} flow={flow} />
        ))}
      </div>
      <StateLegend />
      <nav className="hub-now" aria-label="Runs needing attention">
        <span className="hub-now-label">Now</span>
        {chips.map((r) => {
          const w = waitingCount(r);
          const state = ACTIVE_STATUSES.has(r.status) ? "now" : w > 0 ? "wait" : "failed";
          const pct = r.company_count > 0 ? Math.round((r.completed_count / r.company_count) * 100) : 0;
          return (
            <a key={r.run_id} className={`hub-chip hub-chip-${state}`} href={runHref(r)}>
              <span className={`hub-dot hub-dot-${state}`} aria-hidden />
              {runTypeLabel(r.run_type)} · {state === "now" ? `running ${pct}%` : state === "wait" ? `${w} waiting on you` : "failed"}
            </a>
          );
        })}
        {known && chips.length === 0 && <span className="muted">Nothing running or waiting.</span>}
        <a className="hub-now-all" href="#/history">
          All runs →
        </a>
      </nav>
    </div>
  );
}

/** A process drawn as its steps in order, like Extraction's pipeline: each
 * card carries the step's live state and opens the screen that does it. */
export function ProcessOverview({ id }: { id: string }) {
  const p = PROCESSES.find((x) => x.id === id)!;
  const { runs, error } = useRuns();
  const { flow, error: flowError } = useHouseFlow();
  const usesFlow = p.steps.some((s) => s.stage);

  return (
    <div className="page hub">
      <p className="hub-crumb">
        <a href="#/home">Start</a> › {p.name}
      </p>
      <h1>{p.name}</h1>
      <p className="help-text">{p.purpose} Open a step to work in its screen.</p>
      {error && <p className="error-text" role="alert">Runs could not be loaded: {error}. Step states are unknown until the backend responds.</p>}
      {usesFlow && flowError && <p className="error-text" role="alert">The stewardship flow could not be loaded: {flowError}. Stage numbers are unknown.</p>}
      <ol className="hub-flow">
        {p.steps.map((s, i) => {
          const state = stepState(s, runs, flow);
          const mine = s.runTypes && runs ? runs.filter((r) => s.runTypes!.includes(r.run_type)).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)) : null;
          const last = mine?.[0];
          const waiting = mine ? mine.reduce((n, r) => n + waitingCount(r), 0) : 0;
          const stage = s.stage ? flow?.stages.find((x) => x.id === s.stage) : undefined;
          const decisions = openCount(stage);
          return (
            <li key={s.label} className="hub-flow-item">
              <a className={`hub-step hub-step-${state}`} href={s.href}>
                <span className="hub-step-head">
                  <span className="hub-step-num">{i + 1}</span>
                  <span className="hub-step-title">{s.label}</span>
                </span>
                {(waiting > 0 || decisions > 0) && (
                  <span className="hub-step-banner">{waiting > 0 ? `${waiting} waiting on you` : `${decisions} decision${decisions === 1 ? "" : "s"} open`}</span>
                )}
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
                    {stage.metrics.slice(0, 2).map((m) => (
                      <span key={m.label}>
                        {m.label}
                        <b>{m.value}</b>
                      </span>
                    ))}
                  </span>
                )}
                {!mine && !stage?.metrics.length && <span className="hub-step-about">{s.about}</span>}
                <span className="hub-step-foot">{s.screen} →</span>
              </a>
            </li>
          );
        })}
      </ol>
      <StateLegend />
    </div>
  );
}
