import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { RunManifest, StewardshipFlow } from "../types";
import { ACTIVE_STATUSES, REVIEWABLE_RUN_TYPES, runTypeLabel, waitingCount, waitingParts } from "../lib/runs";
import { openCount } from "./steward/common";

// The start page and the three process overview pages. A process is a named
// group of screens in order; each step links to the screen that does it and
// reads its live state from the runs list (or, for StewardIQ, the house
// stewardship flow). Data Engineer has no overview page: its box opens
// Extraction, which already draws its own pipeline.
type Step = { label: string; screen: string; href: string; about: string; runTypes?: string[]; stage?: string };
// `code` prefixes the process's serial number in the start-page register.
type Process = { id: string; code: string; name: string; purpose: string; href: string; runTypes: string[]; steps: Step[] };


const PROCESSES: Process[] = [
  {
    id: "stewardiq",
    code: "SIQ",
    name: "StewardIQ",
    purpose: "Monitor holdings, engage companies, vote, and track what they commit to.",
    href: "#/stewardiq",
    runTypes: ["proxy_voting"],
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
    code: "TM",
    name: "Theme Machine",
    purpose: "Spot emerging themes, define them as taxonomies, and match companies to them.",
    href: "#/themeMachine",
    runTypes: ["emerging_themes", "taxonomy_research", "theme"],
    steps: [
      { label: "Spot", screen: "Emerging Themes", href: "#/emergingThemes", runTypes: ["emerging_themes"], about: "Candidate themes from filings and news." },
      { label: "Define", screen: "Taxonomy Library", href: "#/taxonomy", runTypes: ["taxonomy_research"], about: "The theme's activities; ratify a version." },
      { label: "Match", screen: "Thematic Universe", href: "#/theme", runTypes: ["theme"], about: "Companies matched to activities, with cited rationale." },
      { label: "Review", screen: "Review Queue", href: "#/review", runTypes: ["theme"], about: "Resolve contested classifications." },
    ],
  },
  {
    id: "dataEngineer",
    code: "DE",
    name: "Data Engineer",
    purpose: "Extract data points from disclosures, each verified and cited against its source.",
    href: "#/extraction",
    runTypes: ["extraction", "financials", "tnfd", "transition_plan"],
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
    code: "DS",
    name: "Design Studio",
    purpose: "Build and ratify scoring templates, then turn the scores into an index.",
    href: "#/designStudio",
    runTypes: ["calibration"],
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

/** What a process waits on a person for, as named parts: ballot items and
 * flagged items from its runs, plus open decisions in its stewardship stages.
 * Every count on the start page is built from these parts, so a total is
 * always shown with what it is made of. */
function processParts(p: Process, runs: RunManifest[], flow: StewardshipFlow | null) {
  const w = waitingParts(runs.filter((r) => p.runTypes.includes(r.run_type)));
  const stages = p.steps.reduce((n, s) => n + (s.stage ? openCount(flow?.stages.find((x) => x.id === s.stage)) : 0), 0);
  return { ...w, stages, total: w.ballots + w.review + stages };
}

function describe(parts: { ballots: number; review: number; stages: number }): string[] {
  const out: string[] = [];
  if (parts.ballots) out.push(`${parts.ballots} ballot item${parts.ballots === 1 ? "" : "s"}`);
  if (parts.review) out.push(`${parts.review} flagged item${parts.review === 1 ? "" : "s"}`);
  if (parts.stages) out.push(`${parts.stages} stage decision${parts.stages === 1 ? "" : "s"}`);
  return out;
}

const joinAnd = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** Where a run row goes: its review, its ballot, or its process. */
function runHref(r: RunManifest): string {
  if (r.review_count > 0 && REVIEWABLE_RUN_TYPES.has(r.run_type)) return `#/review/${r.run_type}/${encodeURIComponent(r.run_id)}`;
  if (r.run_type === "proxy_voting") return `#/voting/${encodeURIComponent(r.run_id)}`;
  return PROCESS_OF_RUN_TYPE.get(r.run_type)?.href ?? "#/history";
}

const WEEK_MS = 7 * 24 * 3600 * 1000;
const recent = (iso: string) => Date.now() - new Date(iso).getTime() < WEEK_MS;

function ago(iso: string): string {
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 60) return `${Math.max(min, 1)} min ago`;
  if (min < 48 * 60) return `${Math.round(min / 60)} h ago`;
  return `${Math.round(min / 1440)} days ago`;
}

const STATE_LABEL: Record<StepState, string> = { done: "has a finished run", now: "running", wait: "awaiting countersignature", failed: "last run void", idle: "no activity yet" };

/** A step mark: a ruled circle, ticked once a run has finished, dashed in
 * stamp violet while it awaits a person, struck through when its run failed. */
function StepMark({ state }: { state: StepState }) {
  return (
    <svg className={`cs-mark cs-mark-${state}`} viewBox="0 0 22 22" aria-hidden>
      <circle cx="11" cy="11" r="8.5" />
      {state === "done" && <path d="M6.5 11.5l3 3 6-6.5" />}
      {state === "now" && <circle className="cs-mark-dot" cx="11" cy="11" r="3.5" />}
      {state === "failed" && <path d="M6 16 16 6" />}
    </svg>
  );
}

/** The engraved rosette: concentric rings crossed by rotated ellipses, the
 * figure security printers use as a seal. Decorative only. */
function Rosette({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 200 200" aria-hidden>
      {[30, 45, 60, 75, 90].map((r) => (
        <circle key={r} cx="100" cy="100" r={r} />
      ))}
      {[0, 30, 60, 90, 120, 150].map((a) => (
        <ellipse key={a} cx="100" cy="100" rx="90" ry="35" transform={`rotate(${a} 100 100)`} />
      ))}
    </svg>
  );
}

function RegisterRow({ p, runs, flow }: { p: Process; runs: RunManifest[] | null; flow: StewardshipFlow | null }) {
  const mine = (runs ?? []).filter((r) => p.runTypes.includes(r.run_type)).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
  const last = mine[0];
  const parts = runs ? processParts(p, runs, flow) : null;
  const states = p.steps.map((s) => stepState(s, runs, flow));
  const serial = `${p.code} ${String(mine.length).padStart(4, "0")}`;
  return (
    <tr>
      <td className="cs-serial" title={`${mine.length} run${mine.length === 1 ? "" : "s"} registered`}>
        {serial}
      </td>
      <th scope="row" className="cs-process">
        <a href={p.href}>{p.name}</a>
        <small>{p.purpose}</small>
      </th>
      <td>
        <span className="cs-marks">
          {states.map((st, i) => (
            <StepMark key={p.steps[i].label} state={st} />
          ))}
        </span>
        <span className="visually-hidden">{p.steps.map((s, i) => `${s.label}: ${STATE_LABEL[states[i]]}`).join("; ")}</span>
      </td>
      <td className="cs-prepared">
        {!runs ? (
          "Unknown"
        ) : !last ? (
          "No runs yet"
        ) : last.status === "failed" ? (
          <>
            <span className="cs-void">Void</span> stopped at {last.completed_count} of {last.company_count}
          </>
        ) : (
          `${runTypeLabel(last.run_type)}, ${ago(last.updated_at)}`
        )}
      </td>
      <td>
        {!parts ? (
          <span className="muted">Unknown</span>
        ) : parts.total > 0 ? (
          <span className="cs-await">
            <span className="cs-sigline" aria-hidden />
            {parts.total} awaiting: {describe(parts).join(", ")}
          </span>
        ) : (
          <span className="muted">Nothing to sign</span>
        )}
      </td>
      <td className="cs-open">
        <a href={p.href} aria-label={`Open ${p.name}`}>
          Open
        </a>
      </td>
    </tr>
  );
}

export function StartPage() {
  const { runs, error, retry } = useRuns();
  const { flow } = useHouseFlow();
  const known = runs !== null;
  const all = runs ?? [];
  const totals = PROCESSES.reduce(
    (t, p) => {
      const x = processParts(p, all, flow);
      return { ballots: t.ballots + x.ballots, review: t.review + x.review, stages: t.stages + x.stages };
    },
    { ballots: 0, review: 0, stages: 0 },
  );
  const due = describe(totals);
  const active = all.filter((r) => ACTIVE_STATUSES.has(r.status));
  const failed = all.filter((r) => r.status === "failed" && recent(r.updated_at));
  const rank = (r: RunManifest) => (ACTIVE_STATUSES.has(r.status) ? 0 : waitingCount(r) > 0 ? 1 : 2);
  const attention = [...new Set([...active, ...all.filter((r) => waitingCount(r) > 0), ...failed])]
    .sort((a, b) => rank(a) - rank(b) || (a.updated_at < b.updated_at ? 1 : -1))
    .slice(0, 8);
  const lastDone = all.filter((r) => DONE.has(r.status)).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0];

  return (
    <div className="page cs-start">
      <section className="cs-band" aria-labelledby="cs-due">
        <Rosette className="cs-rosette" />
        <h2 id="cs-due">
          {!known ? (
            "Status unknown until the runs load."
          ) : due.length ? (
            <>
              {joinAnd(due)
                .split(/(\d+)/)
                .map((chunk, i) => (i % 2 ? <em key={i}>{chunk}</em> : chunk))}{" "}
              await countersignature.
            </>
          ) : (
            "Nothing awaits countersignature."
          )}
        </h2>
        <p className="cs-asof">
          As of {new Date().toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
          {known && active.length > 0 && ` · ${active.length} run${active.length === 1 ? "" : "s"} in progress`}
          {known && failed.length > 0 && ` · ${failed.length} run${failed.length === 1 ? "" : "s"} void this week`}
          {known && !due.length && lastDone && ` · last run finished ${ago(lastDone.updated_at)}`}
        </p>
      </section>
      {error && (
        <p className="error-text" role="alert">
          Runs could not be loaded: {error}. {known ? "Showing the last answer." : "Counts are unknown until the backend responds."}{" "}
          <button className="link-button" onClick={retry}>
            Retry
          </button>
        </p>
      )}

      <section aria-labelledby="cs-register">
        <div className="cs-head">
          <h3 id="cs-register">Register of processes</h3>
          <span className="muted">Prepared by agents, countersigned by people</span>
        </div>
        <table className="cs-table">
          <thead>
            <tr>
              <th scope="col">No.</th>
              <th scope="col">Process</th>
              <th scope="col">Steps</th>
              <th scope="col">Prepared</th>
              <th scope="col">Countersign</th>
              <th scope="col">
                <span className="visually-hidden">Open</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {PROCESSES.map((p) => (
              <RegisterRow key={p.id} p={p} runs={runs} flow={flow} />
            ))}
          </tbody>
        </table>
        <p className="cs-legend muted">
          <StepMark state="done" /> finished run <StepMark state="now" /> running <StepMark state="wait" /> awaiting countersignature <StepMark state="failed" /> void
        </p>
      </section>

      <section aria-labelledby="cs-runs">
        <div className="cs-head">
          <h3 id="cs-runs">Runs needing attention</h3>
          <a href="#/history">All runs</a>
        </div>
        {!known ? (
          <p className="muted">Unknown until the runs load.</p>
        ) : attention.length === 0 ? (
          <p className="muted">Nothing running, awaiting a person or void.</p>
        ) : (
          <table className="cs-table cs-runs">
            <tbody>
              {attention.map((r) => {
                const pct = r.company_count > 0 ? Math.round((r.completed_count / r.company_count) * 100) : 0;
                const w = waitingCount(r);
                const state = ACTIVE_STATUSES.has(r.status) ? "running" : w > 0 ? "awaiting" : r.status === "failed" ? "void" : r.status;
                return (
                  <tr key={r.run_id}>
                    <td className="cs-serial">{PROCESS_OF_RUN_TYPE.get(r.run_type)?.code ?? "RUN"}</td>
                    <th scope="row" className="cs-process">
                      <a href={runHref(r)}>{runTypeLabel(r.run_type)}</a>
                      <small>
                        {r.completed_count} of {r.company_count} companies{w > 0 ? `, ${w} awaiting a person` : ""}
                        {r.status === "failed" && r.error ? `, ${r.error}` : ""}
                      </small>
                    </th>
                    <td className="cs-progress">
                      <span className="progress-bar" aria-hidden>
                        <span className="progress-bar-fill" style={{ transform: `scaleX(${pct / 100})` }} />
                      </span>
                    </td>
                    <td className="cs-state">
                      {state === "void" ? <span className="cs-void">Void</span> : <span className={`cs-tag cs-tag-${state}`}>{state}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
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
      <h2>{p.name}</h2>
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
      <p className="muted hub-legend">
        <span className="hub-key done" /> has a finished run <span className="hub-key now" /> running <span className="hub-key wait" /> waiting on a person <span className="hub-key failed" /> last run failed
      </p>
    </div>
  );
}
