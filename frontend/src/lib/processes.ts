// The one registry of workspaces and the business processes they run. The
// start page, the workspace pages and the process bar all read it, so a
// process changes in one place. A step links to the screen that does the
// work (often in another workspace: processes cross boxes) and names what it
// hands to the next step; `carried: false` marks a handoff re-entered by hand.
// Live state comes from the run store (`runTypes`) or the house stewardship
// flow (`stage`). See docs/PROCESS_VIEW.md.

export type Step = {
  tab: string;
  sub?: string; // deep-link param, e.g. a Steward Workflow stage
  label: string;
  does: string;
  handsOn?: string;
  carried?: boolean;
  runTypes?: string[];
  /** A Steward Workflow stage whose open decisions this step owns. */
  stage?: string;
  /** Its flagged items wait on a later step (the Review Queue), so its state shows only running/failed/done. */
  reviewedElsewhere?: boolean;
  optional?: boolean;
};
export type Process = { id: string; title: string; cadence: string; outcome: string; steps: Step[] };
export type WorkspaceId = "stewardiq" | "argus" | "transitionIntel" | "rdLab" | "dataHub";
export type Workspace = {
  id: WorkspaceId;
  name: string;
  purpose: string;
  /** Runs this workspace produces: its card's waiting/failed/running counts. */
  runTypes: string[];
  processes: Process[];
  /** Every screen of the workspace, for running a single step by hand. */
  screens: [href: string, label: string][];
};

const REVIEWABLE = ["theme", "extraction", "financials", "identity"];
const EXTRACTION_RUNS = ["extraction", "financials", "tnfd", "transition_plan"];

export const WORKSPACES: Workspace[] = [
  {
    id: "stewardiq",
    name: "StewardIQ",
    purpose: "Engage companies, vote, and track what they commit to.",
    runTypes: ["proxy_voting"],
    screens: [
      ["#/stewardship", "Steward Workflow"],
      ["#/engagement", "Engagement"],
      ["#/voting", "Proxy Voting"],
    ],
    processes: [
      {
        id: "engage",
        title: "Engage and escalate",
        cadence: "Continuous",
        outcome: "Every issue has an owner, a next step and a documented escalation path.",
        steps: [
          { tab: "stewardship", sub: "monitoring", stage: "monitoring", label: "Monitoring", does: "Triggers on holdings (incl. Risk Monitoring alerts and votes against management), checked against house policy.", handsOn: "Triggers", carried: true },
          { tab: "stewardship", sub: "selection", stage: "selection", label: "Selection", does: "Coverage rules, reading published tiers, decide who is engaged this cycle.", handsOn: "Engagement program", carried: true },
          { tab: "engagement", label: "Engagement", does: "Issue record: contacts, severity, milestone and escalation stage.", handsOn: "Issue record", carried: true },
          { tab: "stewardship", sub: "drafting", stage: "drafting", label: "Drafting", does: "Dossier, outreach letter and talking points; a person approves before sending.", handsOn: "Sent outreach", carried: true },
          { tab: "stewardship", sub: "tracking", stage: "tracking", label: "Tracking", does: "Commitments verified or missed; missed ones escalate and loop back to monitoring." },
        ],
      },
      {
        id: "proxy",
        title: "Proxy season",
        cadence: "Per meeting, peaks March–June",
        outcome: "Voting intentions published, votes cast checked against policy, outcomes fed into engagement.",
        steps: [
          { tab: "voting", label: "Proxy Voting", does: "Start a run from meeting agendas; the policy drafts a vote per resolution, a person decides.", handsOn: "Decided ballots", carried: true, runTypes: ["proxy_voting"] },
          // Ballots are counted on the Proxy Voting step, so this stage carries no `stage` (no double count).
          { tab: "stewardship", sub: "voting", label: "Steward · Voting", does: "Decided ballots next to the house policy behind them.", handsOn: "Votes against policy", carried: true },
          { tab: "stewardship", sub: "checkpoint", stage: "checkpoint", label: "Checkpoint", does: "Review every vote decided against the policy's recommendation, with its reason.", handsOn: "Votes against management", carried: true },
          { tab: "engagement", label: "Engagement", does: "A vote against management raises a vote_outcome trigger; open the engagement from Monitoring." },
        ],
      },
      {
        id: "client",
        title: "Client reporting",
        cadence: "Quarterly",
        outcome: "A client report showing house activity plus only where the client's policy differed.",
        steps: [
          { tab: "stewardship", sub: "program", stage: "program", label: "Client program", does: "Calibrate the client's program on its benchmark; approve it.", handsOn: "Client stream", carried: true },
          { tab: "stewardship", sub: "client_policy", stage: "client_policy", label: "Client policy", does: "Decide each exception where the client policy differs from the house.", handsOn: "Exceptions", carried: true },
          { tab: "stewardship", sub: "reporting", stage: "reporting", label: "Reporting", does: "Client report assembled from house truth plus exceptions; export pptx.", handsOn: "Report data" },
          { tab: "reporting", label: "Presentations & Reports", does: "Restyle into the client's template if needed." },
        ],
      },
    ],
  },
  {
    id: "argus",
    name: "Argus",
    purpose: "Extract data points from disclosures, each cited to its source, and score them.",
    runTypes: EXTRACTION_RUNS,
    screens: [
      ["#/extraction", "Extraction"],
      ["#/transitionPlan", "Transition Plan extraction"],
      ["#/review", "Review Queue"],
    ],
    processes: [
      {
        id: "extract",
        title: "Extract and score",
        cadence: "Per universe, refreshed when disclosures change",
        outcome: "Every company resolved and documented, every figure cited to a verified source, every flagged one reviewed, and tiers from a ratified template.",
        // The Extraction screen's own staged flow; each step opens its tab. Companies with
        // documents already on file skip Identify and Documents.
        steps: [
          { tab: "extraction", sub: "companies", label: "Companies", does: "Pick the universe: upload, paste, or take one handed over from Data Hub, Risk Monitoring or Thematic Universe.", handsOn: "Companies", carried: true },
          { tab: "extraction", sub: "identify", label: "Identify", does: "Resolve each company to one issuer; ambiguous matches wait for review.", handsOn: "Resolved companies", carried: true, runTypes: ["identity"] },
          { tab: "extraction", sub: "documents", label: "Documents", does: "Discover and download annual, sustainability and proxy reports, or upload your own by type.", handsOn: "Documents", carried: true, runTypes: ["discovery"] },
          { tab: "extraction", sub: "schema", label: "Schema", optional: true, does: "Custom profile only: the data points to extract and their types.", handsOn: "Schema", carried: true },
          { tab: "extraction", sub: "extract", label: "Extract", does: "Custom schema, Financials, TNFD or Transition plan profile; every citation re-verified against its source.", handsOn: "Flagged figures", carried: true, runTypes: EXTRACTION_RUNS, reviewedElsewhere: true },
          { tab: "review", label: "Review", does: "Approve, edit or reject every flagged figure.", handsOn: "Reviewed figures", carried: true, runTypes: REVIEWABLE },
          { tab: "extraction", sub: "extract", label: "Score", optional: true, does: "Attach a ratified Decision Studio template at setup (or after the run); publish the tiers from the run's Scoring panel.", handsOn: "Published tiers", carried: true },
          { tab: "decision", label: "Template", optional: true, does: "Build and ratify scoring templates in Decision Studio (R&D Lab); only ratified versions reach Argus." },
        ],
      },
    ],
  },
  {
    id: "transitionIntel",
    name: "Transition Intelligence Platform",
    purpose: "Monitor holdings and assess climate and transition risk.",
    runTypes: ["transition_barrier_refresh"],
    screens: [
      ["#/portfolio-monitoring", "Risk Monitoring"],
      ["#/transitionBarrier", "Transition Barriers"],
      ["#/transitionPlan", "Transition Plan"],
    ],
    processes: [
      {
        id: "monitor",
        title: "Monthly monitoring",
        cadence: "Monthly, after the holdings and ESG loads",
        outcome: "Every threshold breach and news controversy on a holding is an alert with an owner.",
        steps: [
          { tab: "portfolio-monitoring", sub: "holdings", label: "Holdings Intake", does: "Load the month's holdings and ESG data; the monthly run starts once both are in.", handsOn: "Month's snapshot", carried: true },
          { tab: "portfolio-monitoring", sub: "monitoring", label: "Monitoring & Alerts", does: "Threshold breaches and news controversies on holdings.", handsOn: "Open alerts", carried: true },
          { tab: "portfolio-monitoring", sub: "dashboards", label: "Dashboards", does: "WACI, financed emissions and coverage by portfolio.", handsOn: "Alerts as company fields", carried: true },
          { tab: "stewardship", sub: "monitoring", label: "Steward · Monitoring", does: "Open alerts raise stewardship triggers; open the engagement in StewardIQ." },
        ],
      },
      {
        id: "climate",
        title: "Climate transition review",
        cadence: "Annual, plus ad hoc before committees",
        outcome: "A tiered list of issuers to engage, each with a walk-vs-talk verdict and sector context.",
        steps: [
          { tab: "portfolio-monitoring", sub: "dashboards", label: "Risk Monitoring", does: "WACI, financed emissions and data coverage: where the carbon sits.", handsOn: "Holdings in scope", carried: true },
          { tab: "transitionBarrier", label: "Transition Barriers", does: "Sector × jurisdiction barriers: what can a company in this sector realistically commit to?", handsOn: "Sector context", runTypes: ["transition_barrier_refresh"] },
          { tab: "transitionPlan", label: "Transition Plan", does: "64 indicators per issuer, walk vs. talk, each with a grounded citation (run by Argus), scored with a ratified template.", handsOn: "Indicator scores and tiers", carried: true, runTypes: ["transition_plan"] },
          { tab: "decision", label: "Decision Studio", does: "Tune the scoring template; ratify it, then publish the tiers.", handsOn: "Published tiers", carried: true },
          { tab: "stewardship", sub: "selection", label: "Steward · Selection", does: "Coverage rules read the published tiers: who gets engaged this cycle.", handsOn: "Engagement program" },
          { tab: "reporting", label: "Presentations & Reports", does: "Committee pack: the tiering with its evidence." },
        ],
      },
    ],
  },
  {
    id: "rdLab",
    name: "R&D Lab",
    purpose: "Spot themes and test strategies, score them, and turn them into indices.",
    runTypes: ["emerging_themes", "taxonomy_research", "theme", "calibration"],
    screens: [
      ["#/emergingThemes", "Emerging Themes"],
      ["#/taxonomy", "Taxonomy Library"],
      ["#/theme", "Thematic Universe"],
      ["#/strategyReplication", "Strategy Replication"],
      ["#/decision", "Decision Studio"],
      ["#/index", "Index Construction"],
    ],
    processes: [
      {
        id: "thematic",
        title: "Launch a thematic product",
        cadence: "Per product idea",
        outcome: "A ratified theme, a reviewed universe and an effective-dated index calibration.",
        steps: [
          { tab: "emergingThemes", label: "Spot", does: "Candidate themes from filings and news, gated on corporate action.", handsOn: "Promoted theme", carried: true, runTypes: ["emerging_themes"] },
          { tab: "taxonomy", label: "Define", does: "The theme's activities; ratify a version.", handsOn: "Ratified taxonomy", carried: true, runTypes: ["taxonomy_research"] },
          { tab: "theme", label: "Match", does: "Companies matched to activities with exposure estimates and cited rationale.", handsOn: "Theme universe", carried: true, runTypes: ["theme"], reviewedElsewhere: true },
          { tab: "review", label: "Review", does: "Resolve contested classifications.", handsOn: "Reviewed universe", carried: true, runTypes: ["theme"] },
          { tab: "decision", label: "Score", does: "Score and tier the universe in Decision Studio; ratify, then publish.", handsOn: "Published scores", carried: true },
          { tab: "index", label: "Construct", does: "Screen, select, weight and cap from the published scores; save an effective-dated calibration.", handsOn: "Index composition", runTypes: ["calibration"] },
          { tab: "reporting", label: "Report", does: "Product committee deck." },
        ],
      },
      {
        id: "strategy",
        title: "Research a strategy",
        cadence: "Per paper or idea",
        outcome: "A strategy tested out of sample, compared to alternatives, and built as an index if it holds.",
        steps: [
          { tab: "strategyReplication", label: "Replicate", does: "Paper to executable spec; backtest with deflated Sharpe and PBO.", handsOn: "Backtest runs" },
          { tab: "decision", label: "Compare", does: "Compare strategies side by side in Decision Studio.", handsOn: "Chosen strategy" },
          { tab: "index", label: "Construct", does: "Implement it as rules with capping and a calibration.", handsOn: "Index composition", runTypes: ["calibration"] },
          { tab: "reporting", label: "Report", does: "Investment committee deck." },
        ],
      },
    ],
  },
  {
    id: "dataHub",
    name: "Data Hub",
    purpose: "Input feeds and stored data; the security master maps every security to its issuer, once, for the whole tool.",
    runTypes: [],
    screens: [
      ["#/feeds", "Feeds"],
      ["#/securityMaster", "Security Master"],
      ["#/portfolio-monitoring/holdings", "Holdings Intake"],
      ["#/library", "Data Library"],
      ["#/search", "Search"],
    ],
    processes: [
      {
        id: "onboard",
        title: "Map securities to issuers",
        cadence: "When the security master or a holding changes",
        outcome: "Every held security mapped to exactly one internal issuer by the security master, and nothing mapped any other way.",
        steps: [
          { tab: "securityMaster", label: "Load security master", does: "Upload the master: internal issuer id plus ISIN, CUSIP, SEDOL, FIGI, LEI or CIK. Replaces the golden source whole.", handsOn: "Identifier map", carried: true },
          { tab: "portfolio-monitoring", sub: "holdings", label: "Map holdings", does: "Each holding's ISIN (or LEI) matched exactly to its internal issuer as it loads.", handsOn: "Mapped holdings", carried: true },
          { tab: "securityMaster", label: "Unmatched", does: "Held securities the master does not know: fix the master, not the holding.", handsOn: "Corrections to the master" },
          { tab: "library", label: "Data Library", does: "The issuer view every workspace reads." },
        ],
      },
    ],
  },
];

export const PROCESSES: Process[] = WORKSPACES.flatMap((w) => w.processes);
export const workspaceOfProcess = (id: string | undefined) => WORKSPACES.find((w) => w.processes.some((p) => p.id === id));

/** Steward Workflow stages owned by a step; their open decisions are what StewardIQ waits on. */
export const DECISION_STAGES: string[] = [...new Set(PROCESSES.flatMap((p) => p.steps.map((s) => s.stage).filter((s): s is string => !!s)))];

export const stepHref = (step: Step) => `#/${[step.tab, step.sub].filter(Boolean).map((p) => encodeURIComponent(p!)).join("/")}`;
