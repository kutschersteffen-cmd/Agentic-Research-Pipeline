import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { AuditLogView } from "../components/AuditLogView";
import { ColumnProfileTable } from "../components/ColumnProfileTable";
import { DecisionResultsTable } from "../components/DecisionResultsTable";
import { DecisionTreeEditor } from "../components/DecisionTreeEditor";
import { MechanismEditor } from "../components/MechanismEditor";
import { LevelGridEditor } from "../components/LevelGridEditor";
import { toLevelsMode } from "../lib/levels";
import { ScoreDistribution } from "../components/ScoreDistribution";
import type {
  PublishedDecision,
  ColumnRole,
  DatasetSummary,
  DecisionComparison,
  DecisionResult,
  Direction,
  EntityDecision,
  EntityMovement,
  EntitySensitivity,
  MechanismConfig,
  AuditEntry,
  RunManifest,
  TemplateMatch,
} from "../types";
import { activatable } from "../lib/activatable";
import { setLeaveGuard } from "../lib/leaveGuard";
import { ConfirmDecision } from "../components/ConfirmDecision";
import { newDimension } from "../lib/dimensions";
import { TIER_STARTER } from "../lib/ruleGraphs";

// The canvas pulls in the JDM editor and, on first use, the 14 MB engine:
// loaded only when the Rules tab opens.
const RuleGraphEditor = lazy(() => import("../components/RuleGraphEditor"));

// Publishing matches rows to issuers by one column. The engine finds these
// names on its own; anything else (an ISIN, a ticker) has to be picked.
const ID_COLUMN_NAMES = ["company_id", "issuer_id", "entity_id", "id"];
/** A Movement row worth showing: the entity changed status, or it was scored
 * in the later table and its tier or score moved. Entities excluded or short
 * of data in both tables are left out: their scores are not used. */
function movedOrChangedStatus(m: EntityMovement): boolean {
  if (m.status_before !== m.status_after) return true;
  return m.status_after === "scored" && (m.tier_delta !== 0 || (m.score_delta ?? 0) !== 0);
}

function defaultIdColumn(dataset: DatasetSummary, config: MechanismConfig): string {
  return (
    dataset.columns.find((c) => ID_COLUMN_NAMES.includes(c.toLowerCase())) ??
    dataset.proposals.find((p) => p.role === "reference")?.column ??
    config.label_column ??
    dataset.columns[0]
  );
}

const withoutLayout = (value: unknown) => JSON.stringify(value, (key, v) => (key === "position" ? undefined : v));

const SUB_TABS = [
  { id: "data", label: "1 · Data" },
  { id: "profile", label: "2 · Profile" },
  { id: "rules", label: "3 · Rules" },
  { id: "mechanism", label: "4 · Mechanism" },
  { id: "tree", label: "5 · Decision tree" },
  { id: "results", label: "6 · Results" },
  { id: "movement", label: "7 · Movement" },
  { id: "audit", label: "8 · Audit" },
] as const;

// `entity` names what one row of the resulting table actually is. Three of
// these are not companies, which is the point: the engine scores rows.
const SOURCES = [
  { id: "transition_plan_run", label: "Transition plan run", entity: "company", needsRun: true, needsRegion: false },
  { id: "extraction_run", label: "Extraction run", entity: "company", needsRun: true, needsRegion: false },
  { id: "financials_run", label: "Financials run", entity: "company", needsRun: true, needsRegion: false },
  { id: "tnfd_run", label: "TNFD run", entity: "company", needsRun: true, needsRegion: false },
  { id: "joined_runs", label: "Joined runs (by company)", entity: "company", needsRun: false, needsRegion: false },
  { id: "theme_run", label: "Thematic universe run", entity: "company", needsRun: true, needsRegion: false },
  { id: "portfolio_snapshot", label: "Portfolio snapshot + climate", entity: "company", needsRun: false, needsRegion: false },
  { id: "transition_barrier", label: "Transition barrier matrix", entity: "sector × region", needsRun: false, needsRegion: true },
  { id: "emerging_themes_run", label: "Emerging themes run", entity: "theme", needsRun: true, needsRegion: false },
  { id: "replication_runs", label: "Strategy replication runs", entity: "strategy", needsRun: false, needsRegion: false },
] as const;

/** "A1, A2, A3 and 61 more": a fit cell has to stay one line on a 64-indicator framework. */
function columnList(columns: string[]): string {
  return columns.length <= 3 ? columns.join(", ") : `${columns.slice(0, 3).join(", ")} and ${columns.length - 3} more`;
}

type Tab = (typeof SUB_TABS)[number]["id"];
type GuideStep = { title: string; detail: ReactNode; done?: boolean; action?: { label: string; run: () => void; disabled?: boolean } };
type Scenario = { id: string; label: string; hint: string; steps: GuideStep[] };

/** The step to do now: the first one not done. A step that cannot be
 * tracked (reading a tab) counts as done once a later step is. */
function currentStep(steps: GuideStep[]): number {
  const lastDone = steps.map((s) => !!s.done).lastIndexOf(true);
  const i = steps.findIndex((s, k) => !s.done && !(s.done === undefined && k < lastDone));
  return i === -1 ? steps.length : i;
}

const BARRIER_REGIONS = ["", "European Union", "United States", "China"];
const JOINABLE_RUN_TYPES = new Set(["transition_plan", "extraction", "financials", "tnfd"]);
const RUN_TYPE_LABEL: Record<string, string> = { transition_plan: "Transition plan", extraction: "Extraction", financials: "Financials", tnfd: "TNFD" };

export function DecisionStudio() {
  const [sub, setSub] = useState<Tab>("data");
  // Tabs opened since the table was selected: the guide's "read the
  // result" steps count as done once their tab has been opened.
  const [seen, setSeen] = useState<Set<Tab>>(new Set());
  const [scenarioId, setScenarioId] = useState("table");
  const [builtFromList, setBuiltFromList] = useState(false);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [dataset, setDataset] = useState<DatasetSummary | null>(null);
  // The table as the framework's rule graph extends it (calculated columns
  // profiled server-side over every row); null when there are no rules.
  const [calculated, setCalculated] = useState<DatasetSummary | null>(null);
  const [config, setConfig] = useState<MechanismConfig | null>(null);
  // The version as the server last returned it. Save, ratify, publish and
  // export all act on that stored version, so an edit on screen that is not
  // saved yet must not look ratified or be publishable.
  const [stored, setStored] = useState<MechanismConfig | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [result, setResult] = useState<DecisionResult | null>(null);
  const [comparison, setComparison] = useState<DecisionComparison | null>(null);
  const [sensitivity, setSensitivity] = useState<EntitySensitivity | null>(null);
  const [orderBy, setOrderBy] = useState<"score" | "leverage">("score");
  const [status, setStatus] = useState("");
  const [confirmingRatify, setConfirmingRatify] = useState(false);
  const [confirmingPublish, setConfirmingPublish] = useState(false);
  const [published, setPublished] = useState<PublishedDecision | null>(null);
  const [idColumn, setIdColumn] = useState("");
  const [error, setError] = useState("");
  const [source, setSource] = useState<string>("transition_plan_run");
  const [runId, setRunId] = useState("");
  const [region, setRegion] = useState("");
  const [compareWith, setCompareWith] = useState("");
  const [baseVersion, setBaseVersion] = useState<number | null>(null);
  const [includeIndicators, setIncludeIndicators] = useState(false);
  // Joined runs: the company-level runs to combine, and the ones to pick from.
  const [joinIds, setJoinIds] = useState<string[]>([]);
  // Finished runs, for the run picker and the join list (loaded on first need).
  const [finished, setFinished] = useState<RunManifest[] | null>(null);
  const joinable = (finished ?? []).filter((r) => JOINABLE_RUN_TYPES.has(r.run_type)).slice(0, 40);
  const [templates, setTemplates] = useState<TemplateMatch[]>([]);
  const scoreTimer = useRef<number | undefined>(undefined);
  const view = calculated ?? dataset;
  // Node positions on the rule canvas are layout, not rules: the server's
  // diff ignores them too, so dragging a node is not an unsaved change.
  const unsaved = config !== null && withoutLayout(config) !== withoutLayout(stored);

  function loadConfig(next: MechanismConfig | null) {
    setConfig(next);
    setStored(next);
  }

  /** True when nothing unsaved would be lost, or the person agrees to lose it. */
  function discardOk() {
    return !unsaved || window.confirm(`Discard the unsaved changes to v${config?.version}? They were never saved, so no version records them.`);
  }

  // Leaving for another screen of the app unmounts this one and its edits.
  useEffect(() => {
    if (!unsaved) return;
    setLeaveGuard(discardOk);
    return () => setLeaveGuard(null);
  });

  useEffect(() => {
    if (!unsaved) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = ""; // older Chromium shows the prompt only when this is set
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsaved]);

  const refreshDatasets = useCallback(async () => {
    try {
      setDatasets(await api.listDecisionDatasets());
    } catch {
      setDatasets([]);
    }
  }, []);

  useEffect(() => {
    refreshDatasets();
  }, [refreshDatasets]);

  // Saved frameworks, each checked against the selected table's columns.
  const refreshTemplates = useCallback(async () => {
    try {
      setTemplates(await api.matchTemplates({ columns: dataset?.columns ?? [] }));
    } catch {
      setTemplates([]);
    }
  }, [dataset]);

  useEffect(() => {
    refreshTemplates();
  }, [refreshTemplates]);

  async function guard<T>(label: string, fn: () => Promise<T>): Promise<T | null> {
    setError("");
    setStatus(label);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setStatus("");
    }
  }

  async function onUpload(file: File) {
    if (!discardOk()) return;
    const summary = await guard("Parsing and profiling…", () => api.uploadDecisionDataset(file));
    if (summary) {
      selectDataset(summary);
      refreshDatasets();
    }
  }

  const needsRuns = source === "joined_runs" || SOURCES.find((s) => s.id === source)?.needsRun;
  useEffect(() => {
    if (!needsRuns || finished) return;
    api
      .listRuns()
      .then((res) => setFinished((res as { runs: RunManifest[] }).runs.filter((r) => r.completed_count > 0)))
      .catch(() => {});
  }, [needsRuns, finished]);

  async function onFromSource() {
    if (!discardOk()) return;
    const summary = await guard("Building the table…", () =>
      api.decisionDatasetFromSource({
        source,
        run_id: runId || undefined,
        region: region || undefined,
        include_indicators: (source === "transition_plan_run" || source === "joined_runs") && includeIndicators,
        run_ids: source === "joined_runs" ? joinIds : undefined,
      }),
    );
    if (summary) {
      selectDataset(summary);
      refreshDatasets();
    }
  }

  async function onSeedDemoRun() {
    const seeded = await guard("Creating a sample run…", () => api.seedTransitionPlanDemo());
    if (seeded) {
      setRunId(seeded.run_id);
      setIncludeIndicators(true);
      setFinished(null); // reload the run picker
      setStatus(`Created sample run ${seeded.run_id}: ${seeded.company_count} fictional companies, made-up verdicts. Build the table to use it.`);
    }
  }

  function selectDataset(summary: DatasetSummary) {
    setDataset(summary);
    setCalculated(null);
    loadConfig(null);
    setResult(null);
    setAudit([]);
    setComparison(null);
    setBaseVersion(null);
    setSeen(new Set());
    // Every route continues with a framework, and that is on this tab.
    show("ds-framework");
  }

  function open(tab: Tab) {
    setSub(tab);
    setSeen((prev) => (prev.has(tab) ? prev : new Set(prev).add(tab)));
  }

  /** Opens the Data tab at one of its two sections. */
  function show(id: "ds-table" | "ds-framework") {
    setSub("data");
    requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: "start" }));
  }

  /** Loads a saved framework onto the selected table. Saving afterwards makes
   * a new version of that framework, diffed against the one loaded. */
  async function onApplyTemplate(match: TemplateMatch) {
    if (!discardOk()) return;
    const envelope = await guard("Loading the template…", () => api.getMechanism(match.config.framework_id, match.config.version));
    if (envelope) {
      loadConfig(envelope.config);
      setAudit(envelope.audit);
      setBaseVersion(envelope.config.version);
      open("results");
    }
  }

  async function onImportTemplate(file: File) {
    const envelope = await guard("Importing the template…", async () =>
      api.importMechanism(JSON.parse(await file.text())),
    );
    if (envelope) {
      setStatus(`Imported ${envelope.config.name} as a draft.`);
      refreshTemplates();
    }
  }

  async function onImportIndicatorList(file: File) {
    const name = file.name.replace(/\.[^.]+$/, "");
    const envelope = await guard("Building the framework…", () => api.importIndicatorList(file, name));
    if (envelope) {
      setBuiltFromList(true);
      setStatus(
        `Built ${envelope.config.name} from ${envelope.config.level_criteria?.length ?? 0} indicators as a draft. ` +
          (dataset ? "Apply it below once its row says fits." : "Next: load the company table it scores."),
      );
      refreshTemplates();
    }
  }

  async function onDerive() {
    if (!dataset) return;
    const name = `Framework for ${dataset.name}`;
    // Deriving again on the same table adds a version to the framework it
    // already has, rather than starting another one with the same name.
    const existing = templates.find((t) => t.config.name === name)?.config.framework_id;
    const envelope = await guard("Deriving the mechanism…", () =>
      api.deriveMechanism({ dataset_id: dataset.dataset_id, name, save: true, framework_id: existing }),
    );
    if (envelope) {
      loadConfig(envelope.config);
      setAudit(envelope.audit);
      // The proposal as derived is already saved. That is what lets the
      // next save diff against it and record which rules a person changed.
      setBaseVersion(envelope.config.version);
      refreshTemplates();
      // A guessed direction silently inverts a ranking, and Profile is
      // where the guesses are flagged: go there first when there are any.
      open(flagged > 0 ? "profile" : "mechanism");
    }
  }

  // Every number on this page comes back from the engine. Editing a rule
  // re-scores server-side rather than recomputing anything locally, so what
  // is on screen is exactly what the audit trail records.
  // Bumped when a reviewer sets or removes a level override, to score again.
  const [overridesTick, setOverridesTick] = useState(0);
  useEffect(() => {
    if (!dataset || !config) return;
    window.clearTimeout(scoreTimer.current);
    scoreTimer.current = window.setTimeout(async () => {
      try {
        setResult(await api.scoreDecision({ dataset_id: dataset.dataset_id, config }));
        setError("");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }, 300);
    return () => window.clearTimeout(scoreTimer.current);
  }, [dataset, config, overridesTick]);

  const ruleGraph = config?.rule_graph;
  useEffect(() => {
    if (!dataset || !ruleGraph) {
      setCalculated(null);
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        setCalculated(await api.calculatedColumns(dataset.dataset_id, ruleGraph));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }, 400);
    return () => window.clearTimeout(timer);
  }, [dataset, ruleGraph]);

  const roles = useMemo(() => {
    const out: Record<string, ColumnRole> = {};
    config?.criteria.forEach((c) => (out[c.column] = "criterion"));
    config?.gates.forEach((g) => (out[g.column] = "gate"));
    return out;
  }, [config]);

  function setRole(column: string, role: ColumnRole) {
    if (!config) return;
    const next: MechanismConfig = {
      ...config,
      criteria: config.criteria.filter((c) => c.column !== column),
      gates: config.gates.filter((g) => g.column !== column),
      label_column: config.label_column === column ? null : config.label_column,
      size_column: config.size_column === column ? null : config.size_column,
      segment_column: config.segment_column === column ? null : config.segment_column,
      // Leaving the segment job also stops the column being the peer cohort.
      normalise_within: config.normalise_within === column && role !== "segment" ? null : config.normalise_within,
    };
    const proposal = view?.proposals.find((p) => p.column === column);
    if (role === "criterion") {
      // Its own dimension, not the first one: joining an unrelated group
      // would split that group's weight. The Mechanism tab can move it.
      const dimension = newDimension(next, column);
      next.dimensions = [...next.dimensions, dimension];
      next.criteria = [
        ...next.criteria,
        {
          column,
          dimension_id: dimension.id,
          weight: 1,
          enabled: true,
          direction: proposal?.direction ?? "higher",
        },
      ];
    } else if (role === "gate") {
      next.gates = [...next.gates, { id: `gate_${column}`, column, op: "is", value: "Yes", outcome: "demote" }];
    } else if (role === "label") {
      next.label_column = column;
    } else if (role === "size") {
      next.size_column = column;
    } else if (role === "segment") {
      next.segment_column = column;
    }
    setConfig(next);
  }

  function setDirection(column: string, direction: Direction) {
    if (!config) return;
    setConfig({ ...config, criteria: config.criteria.map((c) => (c.column === column ? { ...c, direction } : c)) });
  }

  async function onSave() {
    if (!config) return;
    const envelope = await guard("Saving a new version…", () =>
      api.saveMechanism({ config, base_version: baseVersion ?? undefined }),
    );
    if (envelope) {
      loadConfig(envelope.config);
      setAudit(envelope.audit);
      setBaseVersion(envelope.config.version);
      refreshTemplates();
    }
  }

  async function onRatify(by: string) {
    setConfirmingRatify(false);
    if (!config) return;
    const saved = await guard("Ratifying…", () => api.ratifyMechanism(config.framework_id, config.version, by));
    if (saved) loadConfig(saved);
  }

  async function onPublish() {
    setConfirmingPublish(false);
    if (!config || !dataset) return;
    const snapshot = await guard("Publishing…", () =>
      api.publishDecision({ dataset_id: dataset.dataset_id, framework_id: config.framework_id, version: config.version, id_column: idColumn || undefined }),
    );
    if (snapshot) setPublished(snapshot);
  }

  async function onExplain(entity: EntityDecision) {
    if (!dataset || !config) return;
    const rows = await guard("Testing how far the weights can move…", () =>
      api.decisionSensitivity({ dataset_id: dataset.dataset_id, config, entity_keys: [entity.entity_key] }),
    );
    if (rows && rows.length > 0) setSensitivity(rows[0]);
  }

  async function onCompare() {
    if (!dataset || !config || !compareWith) return;
    const result = await guard("Comparing snapshots…", () =>
      api.compareDecisions({ dataset_id_before: compareWith, dataset_id_after: dataset.dataset_id, config }),
    );
    if (result) setComparison(result);
  }

  async function onExport() {
    if (!dataset || !config) return;
    const response = await fetch(api.decisionExportUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataset_id: dataset.dataset_id, config }),
    });
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${dataset.name.replace(/\.[^.]+$/, "")}_decision.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  // Derivation entries come from deriving or from the stored framework;
  // cut-points and sufficiency notes are added when the mechanism is
  // applied. The log is only useful as one list.
  const auditEntries = useMemo(() => {
    const seen = new Set<string>();
    return [...audit, ...(result?.audit ?? [])].filter((entry) => {
      const key = `${entry.stage}|${entry.item}|${entry.decision}|${entry.why}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [audit, result]);

  const flagged = dataset?.proposals.filter((p) => p.needs_check).length ?? 0;

  // What to do next, for each thing a person might arrive with.
  const hasTable = !!dataset;
  const hasFramework = !!config;
  const read = (tab: Tab) => hasFramework && seen.has(tab);
  const toTable = { label: "Go to the table", run: () => show("ds-table") };
  const toFramework = { label: "Go to frameworks", run: () => show("ds-framework") };
  const loadTable: GuideStep = {
    title: "Load the company table",
    detail: (
      <>
        Upload it under <em>The table to score</em>: one row per company, one column per indicator.
      </>
    ),
    done: hasTable,
    action: toTable,
  };
  const readResults: GuideStep = {
    title: "Read the outcome on Results",
    detail: "The tier counts, the ranked list, and why each company landed where it did.",
    done: read("results") || undefined,
    action: { label: "Open Results", run: () => open("results"), disabled: !hasFramework },
  };
  const ratify: GuideStep = {
    title: "Save and ratify the version on Audit",
    detail: "A ratified version is fixed, and only a ratified version can be published to stewardship and index.",
    done: !!config?.ratified && !unsaved,
    action: { label: "Open Audit", run: () => open("audit"), disabled: !hasFramework },
  };
  const scenarios: Scenario[] = [
    {
      id: "table",
      label: "A company table",
      hint: "No framework yet. The studio proposes one from the columns.",
      steps: [
        loadTable,
        {
          title: "Derive a framework from the table",
          detail: "Every column gets a proposed job (scored, gate, label…) and a direction.",
          done: hasFramework,
          action: { label: "Derive a framework", run: onDerive, disabled: !hasTable },
        },
        {
          title: "Check the flagged directions on Profile",
          detail: "A wrong direction inverts the ranking, and nothing on screen looks wrong.",
          done: read("profile") || undefined,
          action: { label: "Open Profile", run: () => open("profile"), disabled: !hasFramework },
        },
        readResults,
        ratify,
      ],
    },
    {
      id: "framework",
      label: "A company table and a framework",
      hint: "Saved here, or a framework file (.json) from another installation.",
      steps: [
        loadTable,
        {
          title: "Apply the framework",
          detail: (
            <>
              Under <em>The framework that scores it</em>, its row must say <strong>fits</strong>. A file from elsewhere: import
              it there first.
            </>
          ),
          done: hasFramework,
          action: toFramework,
        },
        readResults,
        ratify,
      ],
    },
    {
      id: "indicators",
      label: "An indicator list",
      hint: "One row per indicator: id, name, group. Company scores come separately.",
      steps: [
        {
          title: "Build a framework from the list",
          detail: (
            <>
              Under <em>The framework that scores it</em>. It is saved as a draft with four placeholder tiers. Format:{" "}
              <code>docs/decision-studio/indicator-list.md</code>.
            </>
          ),
          done: builtFromList || hasFramework,
          action: toFramework,
        },
        {
          title: "Load the company table",
          detail: "One row per company, one column per indicator, each column named exactly as the indicator id.",
          done: hasTable,
          action: toTable,
        },
        {
          title: "Apply the framework you built",
          detail: (
            <>
              Its row says <strong>fits</strong> once the table has every indicator column; otherwise it names the missing ones.
            </>
          ),
          done: hasFramework,
          action: toFramework,
        },
        {
          title: "Name the tiers on Decision tree",
          detail: "The list gives them placeholder names, Tier 1 to Tier 4.",
          done: read("tree"),
          action: { label: "Open Decision tree", run: () => open("tree"), disabled: !hasFramework },
        },
        readResults,
        ratify,
      ],
    },
    {
      id: "run",
      label: "A finished run here",
      hint: "Transition plan, extraction, financials, TNFD and the other run types.",
      steps: [
        {
          title: "Build the table from the run",
          detail: (
            <>
              Under <em>The table to score</em>, pick the run type and the run. To score single transition-plan indicators,
              tick <em>One Yes/No column per indicator</em>.
            </>
          ),
          done: hasTable,
          action: toTable,
        },
        {
          title: "Apply a saved framework, or derive one",
          detail: "Apply when a saved framework fits the table; derive when none does.",
          done: hasFramework,
          action: toFramework,
        },
        readResults,
        ratify,
      ],
    },
    {
      id: "compare",
      label: "Two snapshots to compare",
      hint: "The same companies at two dates, judged by one framework.",
      steps: [
        {
          title: "Load both tables",
          detail: "Upload each file, or build each from its run.",
          done: datasets.length >= 2,
          action: toTable,
        },
        {
          title: "Select the later table and apply the framework",
          detail: "Use the framework the earlier decision was made with.",
          done: hasFramework,
          action: toFramework,
        },
        {
          title: "Compare on Movement",
          detail: "Pick the earlier table. The framework stays fixed, so a move reflects the companies, not the rules.",
          done: !!comparison,
          action: { label: "Open Movement", run: () => open("movement"), disabled: !hasFramework },
        },
      ],
    },
  ];
  const scenario = scenarios.find((x) => x.id === scenarioId) ?? scenarios[0];
  const now = currentStep(scenario.steps);
  const nextStep = scenario.steps[now];

  return (
    <div className="page">
      <h1>Decision Studio</h1>
      <p className="help-text">Turn any per-company table into a scored, ranked and tiered decision. The numbers are computed deterministically, with no LLM, and every automated choice and edit is recorded.</p>

      <div className="sub-nav" role="tablist" aria-label="Decision Studio steps">
        {SUB_TABS.map((tab) => (
          <button
            key={tab.id}
            className={tab.id === sub ? "nav-tab active" : "nav-tab"} role="tab" aria-selected={tab.id === sub}
            onClick={() => open(tab.id)}
            disabled={tab.id !== "data" && !dataset}
            title={tab.id !== "data" && !dataset ? "Load or select a table on the Data tab first" : undefined}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {status && <p className="status-text" role="status">{status}</p>}
      {error && <p className="error-text" role="alert">{error}</p>}

      {dataset && (
        <div className="toolbar decision-context">
          <span>
            <strong>{dataset.name}</strong> — {dataset.row_count} rows, {dataset.columns.length} columns
          </span>
          {dataset.has_confidence && <span className="badge badge-high">carries per-cell confidence</span>}
          <span className="muted">
            {config
              ? `${config.name} v${config.version} ${unsaved ? "(unsaved changes)" : config.ratified ? "(ratified)" : "(draft)"}`
              : "No framework yet"}
          </span>
          {unsaved && <button onClick={onSave}>Save as new version</button>}
        </div>
      )}
      {sub !== "data" && nextStep && (
        <p className="ds-next">
          <span>
            <span className="ds-next-label">Next</span> {nextStep.title}
          </span>
          {nextStep.action && (
            <button className="secondary" onClick={nextStep.action.run} disabled={nextStep.action.disabled}>
              {nextStep.action.label}
            </button>
          )}
        </p>
      )}

      {sub === "data" && (
        <>
          <section className="card ds-guide" aria-labelledby="ds-guide-title">
            <h2 id="ds-guide-title">What are you starting with?</h2>
            <div className="ds-scenarios" role="radiogroup" aria-labelledby="ds-guide-title">
              {scenarios.map((x) => (
                <label key={x.id} className="ds-scenario">
                  <input type="radio" name="ds-scenario" value={x.id} checked={x.id === scenario.id} onChange={() => setScenarioId(x.id)} />
                  <span className="ds-scenario-label">{x.label}</span>
                  <span className="ds-scenario-hint">{x.hint}</span>
                </label>
              ))}
            </div>
            <ol className="ds-steps" aria-label={`Steps for: ${scenario.label}`}>
              {scenario.steps.map((step, i) => {
                const state = i < now || step.done ? "done" : i === now ? "now" : "later";
                return (
                  <li key={step.title} className={`ds-step ds-step-${state}`} aria-current={state === "now" ? "step" : undefined}>
                    <div className="ds-step-text">
                      <span>
                        <strong>{step.title}</strong>
                        {state === "done" && <span className="ds-step-state"> · done</span>}
                      </span>
                      <span className="ds-step-detail">{step.detail}</span>
                    </div>
                    {state === "now" && step.action && (
                      <button onClick={step.action.run} disabled={step.action.disabled}>
                        {step.action.label}
                      </button>
                    )}
                  </li>
                );
              })}
            </ol>
            {now === scenario.steps.length && <p className="status-text">Every step is done for this route.</p>}
          </section>

          <section className="card" id="ds-table" aria-labelledby="ds-table-title">
            <h2 id="ds-table-title">The table to score</h2>
            <p className="help-text">
              One row per company (or sector, theme, strategy), one column per indicator. CSV, TSV or Excel; semicolon
              delimiters and comma decimals are read correctly, so a German-locale export needs no cleaning.
            </p>
            <label className="field-label">
              Upload a file
              <input type="file" accept=".csv,.tsv,.txt,.xlsx,.xls" onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])} />
            </label>

            <h3>Or build it from a finished run</h3>
            <div className="inline-fields">
              <select aria-label="Source run type" value={source} onChange={(e) => setSource(e.target.value)}>
                {SOURCES.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
              {SOURCES.find((s) => s.id === source)?.needsRun && (
                <>
                  {/* Pick from this type's finished runs, or paste any run id. */}
                  <input aria-label="Run id" placeholder="Pick or paste a run id" list="ds-runs" value={runId} onChange={(e) => setRunId(e.target.value)} />
                  <datalist id="ds-runs">
                    {(finished ?? [])
                      .filter((r) => r.run_type === source.replace(/_run$/, ""))
                      .map((r) => (
                        <option key={r.run_id} value={r.run_id}>
                          {`${r.completed_count} companies · ${new Date(r.updated_at).toLocaleDateString()}`}
                        </option>
                      ))}
                  </datalist>
                </>
              )}
              {SOURCES.find((s) => s.id === source)?.needsRegion && (
                <select aria-label="Region" value={region} onChange={(e) => setRegion(e.target.value)}>
                  {BARRIER_REGIONS.map((r) => (
                    <option key={r} value={r}>
                      {r || "All regions"}
                    </option>
                  ))}
                </select>
              )}
              {(source === "transition_plan_run" || source === "joined_runs") && (
                <label>
                  <input type="checkbox" checked={includeIndicators} onChange={(e) => setIncludeIndicators(e.target.checked)} /> One
                  Yes/No column per indicator
                </label>
              )}
              <button
                className="secondary"
                onClick={onFromSource}
                disabled={(source === "joined_runs" && joinIds.length < 2) || (!!SOURCES.find((s) => s.id === source)?.needsRun && !runId.trim())}
              >
                Build the table
              </button>
            </div>
            {source === "transition_plan_run" && (
              <p className="help-text">
                Nothing to test with yet?{" "}
                <button className="link-button" onClick={onSeedDemoRun}>
                  Create a sample run
                </button>{" "}
                with made-up verdicts for 8 fictional companies. No documents or LLM calls.
              </p>
            )}
            {source === "joined_runs" && (
              <div className="join-picker">
                <p className="help-text">
                  Pick two or more runs. Rows are matched on the company id, or on the name when a run has none; a company
                  missing from a run gets blank cells for that run&apos;s columns. A column two runs share (confidence, review
                  flag) takes each run&apos;s prefix — <code>TP_</code>, <code>Extraction_</code>, <code>Financials_</code>,{" "}
                  <code>TNFD_</code>.
                </p>
                {joinable.length === 0 && <p className="muted">No finished Transition Plan, Extraction, Financials or TNFD runs yet.</p>}
                {joinable.map((r) => (
                  <label key={r.run_id} className="join-run">
                    <input
                      type="checkbox"
                      checked={joinIds.includes(r.run_id)}
                      onChange={(e) => setJoinIds(e.target.checked ? [...joinIds, r.run_id] : joinIds.filter((id) => id !== r.run_id))}
                    />
                    <span>{RUN_TYPE_LABEL[r.run_type] ?? r.run_type}</span>
                    <code>{r.run_id}</code>
                    <span className="muted">
                      {r.completed_count} companies · {new Date(r.created_at).toLocaleDateString()}
                    </span>
                  </label>
                ))}
              </div>
            )}
            <p className="help-text">One row per {SOURCES.find((s) => s.id === source)?.entity} in the table this source builds.</p>

            {datasets.length > 0 && (
              <>
                <h3>Tables loaded so far</h3>
                <p className="help-text">Select one to score it. A framework is applied to the selected table.</p>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Source</th>
                        <th>As of</th>
                        <th>Rows</th>
                        <th>
                          <span className="visually-hidden">Selection</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {datasets.map((d) => {
                        const selected = d.dataset_id === dataset?.dataset_id;
                        return (
                          <tr
                            key={d.dataset_id}
                            className={selected ? "clickable-row ds-selected" : "clickable-row"}
                            aria-selected={selected}
                            {...activatable(() => !selected && discardOk() && selectDataset(d))}
                          >
                            <td>{d.name}</td>
                            <td className="muted">{d.source}</td>
                            <td className="muted">{d.as_of ?? "—"}</td>
                            <td>{d.row_count}</td>
                            <td>{selected ? <strong>Selected</strong> : <span className="ds-row-action">Select</span>}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>

          <section className="card" id="ds-framework" aria-labelledby="ds-framework-title">
            <h2 id="ds-framework-title">The framework that scores it</h2>
            <p className="help-text">
              A framework decides which columns count, how they are weighted and where the tiers cut. Each save is a
              numbered version; a ratified version never changes. A saved framework can also be attached to an Extraction,
              Financials, TNFD or Transition Plan run when you start it.
            </p>

            <h3>Apply a saved framework</h3>
            {!dataset && templates.length > 0 && <p className="help-text">Load or select a table above first; then each framework shows whether it fits.</p>}
            {templates.length === 0 ? (
              <p className="muted">No saved frameworks yet. Make one below.</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Framework</th>
                      <th>Status</th>
                      <th>Fit to the selected table</th>
                      <th>
                        <span className="visually-hidden">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {templates.map((t) => {
                      const fits = !!dataset && t.missing_columns.length === 0;
                      return (
                        <tr key={t.config.framework_id}>
                          <td>
                            {t.config.name} v{t.config.version}
                          </td>
                          <td className="muted">{t.config.ratified ? `ratified${t.config.ratified_by ? ` by ${t.config.ratified_by}` : ""}` : "draft"}</td>
                          <td className={fits ? "" : "muted"} title={dataset && !fits ? t.missing_columns.join(", ") : undefined}>
                            {!dataset ? "—" : fits ? <strong>fits</strong> : `missing ${columnList(t.missing_columns)}`}
                          </td>
                          <td className="ds-row-actions">
                            {fits && (
                              <button className="secondary" onClick={() => onApplyTemplate(t)}>
                                Apply
                              </button>
                            )}
                            <a href={api.exportMechanismUrl(t.config.framework_id, t.config.version)}>Export</a>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <h3>Or make a new one</h3>
            <div className="ds-make">
              <div className="ds-make-option">
                <strong>From the selected table</strong>
                <p className="help-text">Proposes a job and direction for every column; you check and edit them.</p>
                <button className="secondary" onClick={onDerive} disabled={!dataset}>
                  Derive a framework
                </button>
              </div>
              <label className="ds-make-option">
                <strong>From an indicator list</strong>
                <span className="help-text">
                  One row per indicator: <code>id</code>, <code>name</code>, <code>group</code>; optionally weights, direction,
                  critical flags and questions (five questions add the credibility grade). No company data needed.
                </span>
                <input
                  type="file"
                  accept=".csv,.tsv,.txt,.xlsx,.xls"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) onImportIndicatorList(file);
                    e.target.value = "";
                  }}
                />
              </label>
              <label className="ds-make-option">
                <strong>From a framework file</strong>
                <span className="help-text">A <code>.json</code> exported from another installation. It arrives as a draft: ratification does not travel with a file.</span>
                <input
                  type="file"
                  accept=".json"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) onImportTemplate(file);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
          </section>
        </>
      )}

      {sub === "profile" && dataset && (
        <div className="card">
          <h2>Every column gets a type, a coverage figure and a job</h2>
          <p className="help-text">
            Types come from the values, not the headers. Direction is the one guess most worth checking — a wrong
            direction inverts the ranking and nothing on the screen looks wrong.
          </p>
          {flagged > 0 && (
            <p className="decision-check-banner">
              {flagged} {flagged === 1 ? "column" : "columns"} flagged: the name gave no clear signal, or gave two
              contradicting ones.
            </p>
          )}
          {config ? (
            <ColumnProfileTable
              profiles={view?.profiles ?? dataset.profiles}
              proposals={view?.proposals ?? dataset.proposals}
              config={config}
              onSetRole={setRole}
              onSetDirection={setDirection}
            />
          ) : (
            <div className="ds-empty">
              <p className="muted">Jobs and directions belong to a framework, and this table has none yet.</p>
              <button onClick={onDerive}>Derive a framework</button>
              <button className="secondary" onClick={() => show("ds-framework")}>Apply a saved one</button>
            </div>
          )}
        </div>
      )}

      {sub === "rules" && dataset && config && (
        <Suspense fallback={<p className="status-text">Loading the rule editor…</p>}>
          <RuleGraphEditor
            graph={config.rule_graph}
            dataset={dataset}
            calculated={calculated}
            labelColumn={config.label_column}
            roles={roles}
            onChange={(rule_graph) => setConfig({ ...config, rule_graph })}
            onSetRole={setRole}
          />
        </Suspense>
      )}
      {sub === "rules" && dataset && !config && (
        <div className="card ds-empty">
          <p className="muted">Rules belong to a framework, and this table has none yet.</p>
          <button onClick={onDerive}>Derive a framework</button>
          <button className="secondary" onClick={() => show("ds-framework")}>Apply a saved one</button>
        </div>
      )}

      {sub === "mechanism" && dataset && config && (
        <>
          <div className="card">
            <h2>How criteria are scored</h2>
            <div className="view-toggle">
              <button
                className={config.mode !== "levels" ? "active" : ""}
                onClick={() => config.mode === "levels" && setConfig({ ...config, mode: "relative", cut_mode: "quantile", pinned_cuts: null })}
              >
                Relative to the other companies
              </button>
              <button className={config.mode === "levels" ? "active" : ""} onClick={() => config.mode !== "levels" && setConfig(toLevelsMode(config))}>
                Fixed levels from rules
              </button>
            </div>
            <p className="help-text">
              {config.mode === "levels"
                ? "Each criterion gets a level from rules over the company's own data, so a score is absolute: the same company scores the same in any table."
                : "Each criterion is normalised against the other companies in the table, so a score says where a company stands in this field."}
            </p>
          </div>
          {config.mode === "levels" ? (
            <LevelGridEditor config={config} columns={(view ?? dataset).columns} onChange={setConfig} />
          ) : (
            <MechanismEditor config={config} profiles={view?.profiles ?? dataset.profiles} weights={result?.effective_weights ?? {}} onChange={setConfig} />
          )}
        </>
      )}

      {sub === "tree" && dataset && config && (
        <>
          <DecisionTreeEditor config={config} profiles={view?.profiles ?? dataset.profiles} result={result} onChange={setConfig} />
          {config.tier_graph ? (
            <Suspense fallback={<p className="status-text">Loading the rule editor…</p>}>
              <RuleGraphEditor
                mode="tiers"
                graph={config.tier_graph}
                dataset={dataset}
                result={result}
                labelColumn={config.label_column}
                onChange={(tier_graph) => setConfig({ ...config, tier_graph })}
              />
            </Suspense>
          ) : (
            <div className="card">
              <div className="toolbar">
                <h2>Tier rules</h2>
                <button className="link-button" onClick={() => setConfig({ ...config, tier_graph: TIER_STARTER })}>
                  Use tier rules instead of demote gates
                </button>
              </div>
              <p className="help-text">
                Decide the final tier with a decision table or formulas instead of the demote gates and dimension floor above —
                for example "coal expansion → worst tier", or "never above Tier 3 below 80% coverage". Each entity&apos;s
                band, score, rank and columns are available. It starts as <code>tier = band</code>, so nothing changes
                until you add a rule. Exclusion gates keep applying first; demote gates and the floor stop.
              </p>
            </div>
          )}
        </>
      )}

      {sub === "results" && config && !result && <p className="status-text">Scoring…</p>}
      {dataset && !config && ["mechanism", "tree", "results", "movement", "audit"].includes(sub) && (
        <div className="card ds-empty">
          <p className="muted">This tab needs a framework, and the selected table has none yet.</p>
          <button onClick={onDerive}>Derive a framework</button>
          <button className="secondary" onClick={() => show("ds-framework")}>Apply a saved one</button>
        </div>
      )}

      {sub === "results" && result && config && (
        <>
          {!!result.missing_columns?.length && (
            <p className="decision-check-banner" role="alert">
              This table lacks columns the framework uses: {result.missing_columns.join(", ")}. A gate on one cannot fire and a
              criterion drops out, so these results cannot be published.
            </p>
          )}
          <div className="decision-kpis">
            {result.tier_summary.map((tier) => (
              <div key={tier.rank} className="card">
                {tier.action && <div className="muted">{tier.action}</div>}
                <h2>{tier.name}</h2>
                <p className="decision-kpi-value">{tier.count}</p>
              </div>
            ))}
            <div className="card">
              <div className="muted">Not scored</div>
              <h2>Gated / insufficient</h2>
              <p className="decision-kpi-value">
                {result.excluded_count} / {result.insufficient_count}
              </p>
            </div>
          </div>

          {config.tier_graph && result.effective_cuts.length > 1 && new Set(result.effective_cuts).size === 1 ? (
            // Every score lands in one band and the tier rules grade it (e.g. the credibility preset).
            <p className="help-text">Tiers here come from the tier rules, not from score cut-points; see each entity's note.</p>
          ) : (
            <div className="card">
              <h2>Score distribution and where the tiers cut</h2>
              <ScoreDistribution bins={result.histogram} cuts={result.effective_cuts} tiers={config.tiers} />
              <p className="help-text">
                Cut-points ({result.cuts_origin}) drawn over the {result.scored_count} entities still eligible after gates
                and sufficiency.
              </p>
            </div>
          )}

          <div className="card">
            <div className="toolbar">
              <h2>Ranked outcome</h2>
              <button className="link-button" onClick={onExport}>
                Export CSV
              </button>
            </div>
            <DecisionResultsTable
              result={result}
              config={config}
              orderBy={orderBy}
              onOrderBy={setOrderBy}
              onExplain={onExplain}
              onSetOverride={async (override) => {
                await api.setDatasetOverride(dataset!.dataset_id, override);
                setOverridesTick((t) => t + 1);
              }}
              onRemoveOverride={async (entityKey, criterionId, _reviewer, reason) => {
                await api.removeDatasetOverride(dataset!.dataset_id, { entity_key: entityKey, criterion_id: criterionId, reason });
                setOverridesTick((t) => t + 1);
              }}
            />
          </div>

          {sensitivity && (
            <div className="card">
              <div className="toolbar">
                <h2>How much do the weights matter — {sensitivity.name}</h2>
                <button className="link-button" onClick={() => setSensitivity(null)}>
                  Close
                </button>
              </div>
              <p className="help-text">
                {sensitivity.min_delta_pct == null
                  ? `Tier ${sensitivity.tier} holds under every weight tested — this placement does not rest on the weights you chose.`
                  : `Tier ${sensitivity.tier} changes after a ${Math.abs(sensitivity.min_delta_pct).toFixed(1)} percentage-point shift in one dimension's weight.`}
              </p>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Dimension</th>
                    <th>Weight now</th>
                    <th>Flips at</th>
                    <th>Change</th>
                    <th>New tier</th>
                  </tr>
                </thead>
                <tbody>
                  {sensitivity.tipping_points.map((point) => (
                    <tr key={point.dimension_id}>
                      <td>{point.dimension_name}</td>
                      <td>{point.current_weight_pct.toFixed(1)}%</td>
                      <td>{point.flip_weight_pct != null ? `${point.flip_weight_pct.toFixed(1)}%` : "—"}</td>
                      <td>{point.delta_pct != null ? `${point.delta_pct > 0 ? "+" : ""}${point.delta_pct.toFixed(1)}pp` : "robust"}</td>
                      <td>{point.new_tier ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {sub === "movement" && dataset && config && (
        <div className="card">
          <h2>What moved since a previous snapshot</h2>
          <p className="help-text">
            Applies this framework, unchanged, to an earlier table. Holding the framework fixed is what makes the
            movement attributable to the companies rather than to a change in how they were judged.
          </p>
          <div className="inline-fields">
            <select value={compareWith} onChange={(e) => setCompareWith(e.target.value)}>
              <option value="">Compare against…</option>
              {datasets
                .filter((d) => d.dataset_id !== dataset.dataset_id)
                .map((d) => (
                  <option key={d.dataset_id} value={d.dataset_id}>
                    {d.as_of ? `${d.as_of} — ${d.name}` : d.name}
                  </option>
                ))}
            </select>
            <button className="link-button" onClick={onCompare} disabled={!compareWith}>
              Compare
            </button>
          </div>

          {comparison && (
            <>
              {!comparison.comparable && <p className="error-text" role="alert">{comparison.incomparable_reason}</p>}
              {comparison.caveat && <p className="decision-check-banner">{comparison.caveat}</p>}
              {!!comparison.missing_columns?.length && (
                <p className="error-text" role="alert">
                  A snapshot lacks columns the framework uses ({comparison.missing_columns.join(", ")}): gates on them cannot fire,
                  so movement for the entities they affect is not reliable.
                </p>
              )}
              <p>
                {comparison.label_before} → {comparison.label_after}: <strong>{comparison.improved}</strong> improved,{" "}
                <strong>{comparison.worsened}</strong> worsened, {comparison.unchanged} unchanged, {comparison.entered} new,{" "}
                {comparison.left} gone.
              </p>
              {comparison.cuts_moved ? (
                <p className="decision-check-banner">{comparison.cuts_moved}</p>
              ) : (
                !!comparison.cut_points?.length && (
                  <p className="muted">
                    Both snapshots tiered on the same cut-points ({comparison.cut_points.map((c) => c.toFixed(1)).join(" / ")}), so a
                    tier changes only when the score does.
                  </p>
                )
              )}
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Tier</th>
                    <th>Score</th>
                    <th>Rank</th>
                    <th>What moved</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.movements
                    .filter(movedOrChangedStatus)
                    .map((movement) => (
                      <tr key={movement.entity_key}>
                        <td>{movement.name}</td>
                        <td>
                          {movement.tier_before ?? "—"} → {movement.tier_after ?? "—"}
                        </td>
                        <td>
                          {movement.score_delta != null
                            ? `${movement.score_delta > 0 ? "+" : ""}${movement.score_delta.toFixed(1)}`
                            : "—"}
                        </td>
                        <td>
                          {movement.rank_delta != null
                            ? `${movement.rank_delta > 0 ? "+" : ""}${movement.rank_delta}`
                            : "—"}
                        </td>
                        <td className="muted">
                          {movement.status_before !== movement.status_after
                            ? `${movement.status_before ?? "not in the table"} → ${movement.status_after ?? "not in the table"}`
                            : movement.drivers.join(", ") || "no single criterion moved much"}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}

      {sub === "audit" && config && (
        <>
          <div className="card">
            <div className="toolbar">
              <h2>Every automated choice, with the basis for it</h2>
              <button className="link-button" onClick={onSave}>
                Save as new version
              </button>
              {baseVersion === config.version && !unsaved && (
                <a href={api.exportMechanismUrl(config.framework_id, config.version)}>Export v{config.version} as template</a>
              )}
              {unsaved ? (
                <span className="muted">
                  Unsaved changes. Save them as a new version to ratify or publish; v{config.version} stays as stored.
                </span>
              ) : config.ratified ? (
                <span className="badge badge-high">
                  Ratified{config.ratified_by ? ` by ${config.ratified_by}` : ""}
                  {config.ratified_at ? ` · ${new Date(config.ratified_at).toLocaleDateString()}` : ""}
                </span>
              ) : (
                <button onClick={() => setConfirmingRatify(true)}>Ratify version {config.version}…</button>
              )}
              {config.ratified && !unsaved && dataset && (
                <button onClick={() => {
                  setIdColumn(defaultIdColumn(dataset, config));
                  setConfirmingPublish(true);
                }}>Publish to stewardship and index…</button>
              )}
            </div>
            {confirmingRatify && (
              <ConfirmDecision
                title={`Ratify version ${config.version}?`}
                confirmLabel={`Ratify version ${config.version}`}
                onConfirm={onRatify}
                onCancel={() => setConfirmingRatify(false)}
              >
                <p>
                  A ratified version is fixed: later edits become a new version, and decisions that cite this one keep
                  reading it exactly as it is now.
                </p>
              </ConfirmDecision>
            )}
            {confirmingPublish && dataset && (
              <ConfirmDecision
                title="Publish these tiers?"
                confirmLabel="Publish"
                onConfirm={onPublish}
                onCancel={() => setConfirmingPublish(false)}
              >
                <p>
                  Freezes version {config.version}'s result on <strong>{dataset.name}</strong>, matched to issuers by their id column. Steward
                  Workflow's coverage rules and Index Construction can then read the tiers and scores. Nothing changes there until a
                  person confirms tiers or runs an index review.
                </p>
                <label className="field-label" htmlFor="publish-id-column">
                  Match issuers by
                </label>
                <select id="publish-id-column" value={idColumn} onChange={(e) => setIdColumn(e.target.value)}>
                  {dataset.columns.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
                {!!result?.missing_columns?.length && (
                  <p className="error-text" role="alert">
                    This table lacks columns the framework uses ({result.missing_columns.join(", ")}), so publishing will be refused.
                  </p>
                )}
                {config.cut_mode !== "absolute" && (
                  <p className="help-text">
                    Cut-points are drawn from the scores. The first publication of version {config.version} fixes them; later
                    publications of this version reuse them, so a tier changes only when the score does.
                  </p>
                )}
              </ConfirmDecision>
            )}
            {published && (
              <p className="status-text" role="status">
                Published {published.rows.length} entities (matched on <code>{published.id_column}</code>) as{" "}
                <code>decision.{published.framework_id}</code>
                {published.cuts_held_from ? ` on the cut-points of its first publication (${published.cut_points?.map((c) => c.toFixed(1)).join(" / ")})` : ""}. Next: <a href="#/stewardship/selection">use the tiers in coverage rules</a> or{" "}
                <a href="#/index">join the scores in an index</a>.
              </p>
            )}
            <p className="help-text">
              A ratified version is never overwritten — later edits become a new version, so the rules a past decision
              cited stay readable exactly as they were.
            </p>
          </div>
          <div className="card">
            <AuditLogView entries={auditEntries} />
          </div>
        </>
      )}
    </div>
  );
}
