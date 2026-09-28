import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RunManifest } from "../types";

// The asset manager's recurring processes, each as the ordered screens that
// carry it. A step names what it hands to the next one and whether that
// handoff is carried by the app today or re-entered by hand ("manual") --
// the manual ones are the gaps to close. See docs/PROCESS_VIEW.md.
type Step = {
  tab: string;
  sub?: string; // deep-link param, e.g. a Steward Workflow stage
  label: string;
  does: string;
  handsOn?: string;
  carried?: boolean;
  runTypes?: string[];
};
type Process = { id: string; title: string; cadence: string; outcome: string; steps: Step[] };

const REVIEWABLE = ["theme", "extraction", "financials", "identity"];

const PROCESSES: Process[] = [
  {
    id: "onboard",
    title: "Onboard a portfolio",
    cadence: "When a fund or mandate is added",
    outcome: "Every holding resolved to one issuer, with current disclosures and reviewed figures.",
    steps: [
      { tab: "identity", label: "Identity Resolution", does: "Upload the holdings list; resolve each line to a canonical issuer.", handsOn: "Resolved universe", carried: true, runTypes: ["identity"] },
      { tab: "discovery", label: "Document Discovery", does: "Find each issuer's IR site and download annual, sustainability and proxy reports.", handsOn: "Disclosure library", runTypes: ["discovery"] },
      { tab: "extraction", label: "Extraction", does: "Company financials (segments, CapEx, R&D) and any schema-defined data points.", handsOn: "Flagged figures", carried: true, runTypes: ["extraction", "financials"] },
      { tab: "review", label: "Review Queue", does: "Approve, edit or reject every flagged figure.", handsOn: "Reviewed figures", carried: true, runTypes: REVIEWABLE },
      { tab: "library", label: "Data Library", does: "Check the issuer view: figures, sources and review history in one place." },
    ],
  },
  {
    id: "climate",
    title: "Climate transition review",
    cadence: "Annual, plus ad hoc before committees",
    outcome: "A tiered list of issuers to engage, each with a walk-vs-talk verdict and sector context.",
    steps: [
      { tab: "portfolio-monitoring", sub: "standard", label: "Risk Monitoring", does: "WACI, financed emissions and data coverage by portfolio: where the carbon sits.", handsOn: "Holdings in scope" },
      { tab: "transitionBarrier", label: "Transition Barriers", does: "Read the sector × jurisdiction barriers first: what can a company in this sector realistically commit to?", handsOn: "Sector context", runTypes: ["transition_barrier_refresh"] },
      { tab: "transitionPlan", label: "Transition Plan", does: "Score 64 indicators per issuer, walk vs. talk, each with a grounded citation.", handsOn: "Indicator scores", carried: true, runTypes: ["transition_plan"] },
      { tab: "decision", label: "Decision Studio", does: "Score and tier issuers from the transition plan run; see rank ranges.", handsOn: "Tiered issuers" },
      { tab: "stewardship", sub: "selection", label: "Steward · Selection", does: "Confirm coverage tiers: who gets engaged this cycle.", handsOn: "Engagement program" },
      { tab: "reporting", label: "Presentations & Reports", does: "Committee pack: the tiering with its evidence." },
    ],
  },
  {
    id: "engage",
    title: "Engage and escalate",
    cadence: "Continuous",
    outcome: "Every issue has an owner, a next step and a documented escalation path.",
    steps: [
      { tab: "portfolio-monitoring", sub: "monitoring", label: "Risk Monitoring · Alerts", does: "News flags and rule breaches on holdings.", handsOn: "Trigger events" },
      { tab: "stewardship", sub: "monitoring", label: "Steward · Monitoring", does: "Triggers evaluated against house policy; open an engagement from one.", handsOn: "Open issue", carried: true },
      { tab: "engagement", label: "Engagement", does: "Issue record: contacts, severity, milestone and escalation stage.", handsOn: "Issue record", carried: true },
      { tab: "stewardship", sub: "drafting", label: "Steward · Drafting", does: "Dossier, outreach letter and talking points; a person approves before sending.", handsOn: "Sent outreach", carried: true },
      { tab: "stewardship", sub: "tracking", label: "Steward · Tracking", does: "Commitments verified or missed; missed ones escalate and loop back to monitoring." },
    ],
  },
  {
    id: "proxy",
    title: "Proxy season",
    cadence: "Per meeting, peaks March–June",
    outcome: "Voting intentions published, votes cast checked against policy, outcomes fed into engagement.",
    steps: [
      { tab: "voting", label: "Proxy Voting", does: "Start a run from meeting agendas; the policy drafts a vote per resolution.", handsOn: "Decided ballots", runTypes: ["proxy_voting"] },
      { tab: "stewardship", sub: "voting", label: "Steward · Voting", does: "Voting intentions and the house policy behind them.", handsOn: "Intentions", carried: true },
      { tab: "stewardship", sub: "checkpoint", label: "Steward · Checkpoint", does: "Votes actually cast reviewed against policy; a named person signs off.", handsOn: "Vote outcomes" },
      { tab: "engagement", label: "Engagement", does: "Failed or contested votes become engagement triggers." },
    ],
  },
  {
    id: "client",
    title: "Client reporting",
    cadence: "Quarterly",
    outcome: "A client report showing house activity plus only where the client's policy differed.",
    steps: [
      { tab: "stewardship", sub: "program", label: "Steward · Client program", does: "Calibrate the client's program on its benchmark; approve it.", handsOn: "Client stream", carried: true },
      { tab: "stewardship", sub: "client_policy", label: "Steward · Client policy", does: "Decide each exception where the client policy differs from the house.", handsOn: "Exceptions", carried: true },
      { tab: "stewardship", sub: "reporting", label: "Steward · Reporting", does: "Client report assembled from house truth plus exceptions; export pptx.", handsOn: "Report data" },
      { tab: "reporting", label: "Presentations & Reports", does: "Restyle into the client's template if needed." },
    ],
  },
  {
    id: "thematic",
    title: "Launch a thematic product",
    cadence: "Per product idea",
    outcome: "A ratified theme, a reviewed universe and an effective-dated index calibration.",
    steps: [
      { tab: "emergingThemes", label: "Emerging Themes", does: "Candidate themes from filings and news, gated on corporate action.", handsOn: "Promoted theme", carried: true, runTypes: ["emerging_themes"] },
      { tab: "taxonomy", label: "Taxonomy Library", does: "Define the theme's activities; ratify a version.", handsOn: "Ratified taxonomy", carried: true, runTypes: ["taxonomy_research"] },
      { tab: "theme", label: "Thematic Universe", does: "Match companies to activities with exposure estimates and cited rationale.", handsOn: "Theme universe", carried: true, runTypes: ["theme"] },
      { tab: "review", label: "Review Queue", does: "Resolve contested classifications.", handsOn: "Reviewed universe", carried: true, runTypes: REVIEWABLE },
      { tab: "decision", label: "Decision Studio", does: "Score and tier the universe (source: thematic universe run).", handsOn: "Scores" },
      { tab: "index", label: "Index Construction", does: "Screens, selection, weighting and caps; save a calibration.", handsOn: "Index composition" },
      { tab: "reporting", label: "Presentations & Reports", does: "Product committee deck." },
    ],
  },
  {
    id: "strategy",
    title: "Research a strategy",
    cadence: "Per paper or idea",
    outcome: "A strategy tested out of sample, compared to alternatives, and built as an index if it holds.",
    steps: [
      { tab: "strategyReplication", label: "Strategy Replication", does: "Paper to executable spec; backtest with deflated Sharpe and PBO.", handsOn: "Backtest runs" },
      { tab: "decision", label: "Decision Studio", does: "Compare strategies side by side (source: strategy replication runs).", handsOn: "Chosen strategy" },
      { tab: "index", label: "Index Construction", does: "Implement it as rules with capping and a calibration.", handsOn: "Index composition" },
      { tab: "reporting", label: "Presentations & Reports", does: "Investment committee deck." },
    ],
  },
];

function latest(runs: RunManifest[], types: string[]) {
  return runs.filter((r) => types.includes(r.run_type)).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0];
}

function StepStatus({ step, runs }: { step: Step; runs: RunManifest[] | null }) {
  if (!step.runTypes) return null;
  if (!runs) return <span className="muted">Status unknown</span>;
  const flagged = runs.filter((r) => step.runTypes!.includes(r.run_type)).reduce((n, r) => n + r.review_count, 0);
  const last = latest(runs, step.runTypes);
  return (
    <span className="process-step-status">
      {last ? (
        <>
          <span className={`status-pill status-${last.status}`}>{last.status}</span>
          <span className="muted">{new Date(last.updated_at).toLocaleDateString()}</span>
        </>
      ) : (
        <span className="muted">No run yet</span>
      )}
      {flagged > 0 && <span className="nav-count" aria-label={`${flagged} awaiting a decision`}>{flagged}</span>}
    </span>
  );
}

export function Processes({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const [runs, setRuns] = useState<RunManifest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const process = PROCESSES.find((p) => p.id === selected) ?? PROCESSES[0];

  useEffect(() => {
    api
      .listRuns()
      .then((res) => setRuns((res as { runs: RunManifest[] }).runs))
      .catch((err) => setError((err as Error).message));
  }, []);

  return (
    <div className="page">
      <h2>Processes</h2>
      <p className="help-text">
        The team's recurring work, each as the screens that carry it in order. Open a step to work in that screen; come back here
        for the next one. A dashed arrow means that handoff is re-entered by hand today.
      </p>
      {error && <p className="error-text">Run status could not be loaded: {error}. Steps still link to their screens.</p>}

      <nav className="sub-nav workflow-tabs" aria-label="Processes">
        {PROCESSES.map((p) => (
          <button key={p.id} className={p.id === process.id ? "nav-tab active" : "nav-tab"} aria-pressed={p.id === process.id} onClick={() => onSelect(p.id)}>
            {p.title}
          </button>
        ))}
      </nav>

      <section className="card">
        <div className="section-heading">
          <h3>{process.title}</h3>
          <span className="chip">{process.cadence}</span>
        </div>
        <p>
          <strong>Done when:</strong> {process.outcome}
        </p>
        <ol className="process-steps">
          {process.steps.map((step, i) => (
            <li key={`${step.tab}-${step.sub ?? i}`} className="process-step">
              <a className="process-step-card" href={`#/${[step.tab, step.sub].filter(Boolean).join("/")}`}>
                <span className="process-step-head">
                  <span className="flow-node-number">{i + 1}</span>
                  <span className="flow-node-title">{step.label}</span>
                </span>
                <span className="process-step-does">{step.does}</span>
                <StepStatus step={step} runs={runs} />
              </a>
              {step.handsOn && i < process.steps.length - 1 && (
                <span className={step.carried ? "process-handoff" : "process-handoff manual"}>
                  {step.handsOn}
                  {!step.carried && " · manual"}
                </span>
              )}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
