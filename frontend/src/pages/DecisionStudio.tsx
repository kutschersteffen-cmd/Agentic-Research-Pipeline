import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  EntitySensitivity,
  MechanismConfig,
  AuditEntry,
  RunManifest,
  TemplateMatch,
} from "../types";
import { activatable } from "../lib/activatable";
import { setLeaveGuard } from "../lib/leaveGuard";
import { useReviewer } from "../lib/reviewer";
import { ConfirmDecision } from "../components/ConfirmDecision";
import { newDimension } from "../lib/dimensions";
import { TIER_STARTER } from "../lib/ruleGraphs";

// The canvas pulls in the JDM editor and, on first use, the 14 MB engine:
// loaded only when the Rules tab opens.
const RuleGraphEditor = lazy(() => import("../components/RuleGraphEditor"));

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

const BARRIER_REGIONS = ["", "European Union", "United States", "China"];
const JOINABLE_RUN_TYPES = new Set(["transition_plan", "extraction", "financials", "tnfd"]);
const RUN_TYPE_LABEL: Record<string, string> = { transition_plan: "Transition plan", extraction: "Extraction", financials: "Financials", tnfd: "TNFD" };

export function DecisionStudio() {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>("data");
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
  const [reviewer] = useReviewer();
  const [confirmingRatify, setConfirmingRatify] = useState(false);
  const [confirmingPublish, setConfirmingPublish] = useState(false);
  const [published, setPublished] = useState<PublishedDecision | null>(null);
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

  function selectDataset(summary: DatasetSummary) {
    setDataset(summary);
    setCalculated(null);
    loadConfig(null);
    setResult(null);
    setAudit([]);
    setComparison(null);
    setBaseVersion(null);
    setSub("profile");
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
      setSub("mechanism");
    }
  }

  async function onImportTemplate(file: File) {
    const envelope = await guard("Importing the template…", async () =>
      api.importMechanism(JSON.parse(await file.text()), reviewer.trim() || undefined),
    );
    if (envelope) {
      setStatus(`Imported ${envelope.config.name} as a draft.`);
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
      setSub(flagged > 0 ? "profile" : "mechanism");
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
      api.saveMechanism({ config, base_version: baseVersion ?? undefined, by: reviewer.trim() || undefined }),
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

  async function onPublish(by: string) {
    setConfirmingPublish(false);
    if (!config || !dataset) return;
    const snapshot = await guard("Publishing…", () =>
      api.publishDecision({ dataset_id: dataset.dataset_id, framework_id: config.framework_id, version: config.version, published_by: by }),
    );
    if (snapshot) setPublished(snapshot);
  }

  async function onExplain(entity: EntityDecision) {
    if (!dataset || !config) return;
    const rows = await guard("Testing how far the weights can move…", () =>
      api.decisionSensitivity({ dataset_id: dataset.dataset_id, config, entity_keys: [entity.entity_key], steps: 9 }),
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

  return (
    <div className="page">
      <h1>Decision Studio</h1>
      <p className="help-text">Turn any per-company table into a scored, ranked and tiered decision. The numbers are computed deterministically, with no LLM, and every automated choice and edit is recorded.</p>

      <div className="sub-nav" role="tablist" aria-label="Decision Studio steps">
        {SUB_TABS.map((tab) => (
          <button
            key={tab.id}
            className={tab.id === sub ? "nav-tab active" : "nav-tab"} role="tab" aria-selected={tab.id === sub}
            onClick={() => setSub(tab.id)}
            disabled={tab.id !== "data" && !dataset}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {status && <p className="status-text">{status}</p>}
      {error && <p className="error-text" role="alert">{error}</p>}

      {dataset && (
        <div className="toolbar decision-context">
          <span>
            <strong>{dataset.name}</strong> — {dataset.row_count} rows, {dataset.columns.length} columns
          </span>
          {dataset.has_confidence && <span className="badge badge-high">carries per-cell confidence</span>}
          {config && (
            <span className="muted">
              {config.name} v{config.version} {unsaved ? "(unsaved changes)" : config.ratified ? "(ratified)" : "(draft)"}
            </span>
          )}
          {!config && <button onClick={onDerive}>Derive a mechanism</button>}
          {unsaved && <button onClick={onSave}>Save as new version</button>}
        </div>
      )}

      {sub === "data" && (
        <div className="card">
          <h3>Load the data the decision rests on</h3>
          <p className="help-text">
            One row per entity, one column per indicator. CSV, TSV or Excel — semicolon delimiters and comma decimals are
            read correctly, so a German-locale export needs no cleaning first. Parsing happens on the server, where the
            result can be reproduced and cited.
          </p>
          <input aria-label="Dataset file" type="file" accept=".csv,.tsv,.txt,.xlsx,.xls" onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])} />

          <h3>…or build it from a run this system already produced</h3>
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
              <select value={region} onChange={(e) => setRegion(e.target.value)}>
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
            <button className="secondary" onClick={onFromSource} disabled={source === "joined_runs" && joinIds.length < 2}>
              Build table
            </button>
          </div>
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
          <p className="help-text">
            One row per {SOURCES.find((s) => s.id === source)?.entity}. Nothing in the engine assumes an entity is a
            company — a sector in a jurisdiction, a theme and a strategy are scored the same way.
          </p>

          {datasets.length > 0 && (
            <>
              <h3>Loaded tables</h3>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Source</th>
                    <th>As of</th>
                    <th>Rows</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {datasets.map((d) => (
                    <tr key={d.dataset_id} className="clickable-row" {...activatable(() => discardOk() && selectDataset(d))}>
                      <td>{d.name}</td>
                      <td className="muted">{d.source}</td>
                      <td className="muted">{d.as_of ?? "—"}</td>
                      <td>{d.row_count}</td>
                      <td>{d.dataset_id === dataset?.dataset_id ? "selected" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <h3>Scoring templates</h3>
          <p className="help-text">
            A saved framework is a template: apply it to the selected table, attach it to an Extraction, Financials, TNFD or Transition Plan run
            when you start one (the run applies it as its last step), or export it as a file for another installation. An imported template starts as a draft —
            ratification does not travel with a file.
          </p>
          <label className="field-label">
            Import a template file
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
          {templates.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Template</th>
                  <th>Status</th>
                  <th>Fit to the selected table</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {templates.map((t) => (
                  <tr key={t.config.framework_id}>
                    <td>
                      {t.config.name} v{t.config.version}
                    </td>
                    <td className="muted">{t.config.ratified ? `ratified${t.config.ratified_by ? ` by ${t.config.ratified_by}` : ""}` : "draft"}</td>
                    <td className="muted">
                      {!dataset ? "select a table" : t.missing_columns.length === 0 ? "fits" : `needs ${t.missing_columns.join(", ")}`}
                    </td>
                    <td>
                      {dataset && t.missing_columns.length === 0 && (
                        <button className="link-button" onClick={() => onApplyTemplate(t)}>
                          Apply
                        </button>
                      )}{" "}
                      <a href={api.exportMechanismUrl(t.config.framework_id, t.config.version)}>Export</a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {sub === "profile" && dataset && (
        <div className="card">
          <h3>Every column gets a type, a coverage figure and a job</h3>
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
            <p className="muted">
              Roles and directions are part of the framework. <button onClick={onDerive}>Derive a mechanism</button>
            </p>
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
        <p className="muted">
          Rules are part of the framework. <button onClick={onDerive}>Derive a mechanism</button>
        </p>
      )}

      {sub === "mechanism" && dataset && config && (
        <>
          <div className="card">
            <h3>How criteria are scored</h3>
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
                <h3>Tier rules</h3>
                <button className="link-button" onClick={() => setConfig({ ...config, tier_graph: TIER_STARTER })}>
                  Use tier rules instead of gates
                </button>
              </div>
              <p className="help-text">
                Decide the final tier with a decision table or formulas instead of the gates and dimension floor above —
                for example "coal expansion → worst tier", or "never above Tier 3 below 80% coverage". Each entity&apos;s
                band, score, rank and columns are available. It starts as <code>tier = band</code>, so nothing changes
                until you add a rule; the gates above stop applying.
              </p>
            </div>
          )}
        </>
      )}

      {sub === "results" && result && config && (
        <>
          <div className="decision-kpis">
            {result.tier_summary.map((tier) => (
              <div key={tier.rank} className="card">
                <div className="muted">{tier.action}</div>
                <h3>{tier.name}</h3>
                <p className="decision-kpi-value">{tier.count}</p>
              </div>
            ))}
            <div className="card">
              <div className="muted">Not scored</div>
              <h3>Gated / insufficient</h3>
              <p className="decision-kpi-value">
                {result.excluded_count} / {result.insufficient_count}
              </p>
            </div>
          </div>

          <div className="card">
            <h3>Score distribution and where the tiers cut</h3>
            <ScoreDistribution bins={result.histogram} cuts={result.effective_cuts} tiers={config.tiers} />
            <p className="help-text">
              Cut-points ({result.cuts_origin}) drawn over the {result.scored_count} entities still eligible after gates
              and sufficiency.
            </p>
          </div>

          <div className="card">
            <div className="toolbar">
              <h3>Ranked outcome</h3>
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
              onRemoveOverride={async (entityKey, criterionId, reviewer, reason) => {
                await api.removeDatasetOverride(dataset!.dataset_id, { entity_key: entityKey, criterion_id: criterionId, reviewer, reason });
                setOverridesTick((t) => t + 1);
              }}
            />
          </div>

          {sensitivity && (
            <div className="card">
              <div className="toolbar">
                <h3>How much do the weights matter — {sensitivity.name}</h3>
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
          <h3>What moved since a previous snapshot</h3>
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
              <p>
                {comparison.label_before} → {comparison.label_after}: <strong>{comparison.improved}</strong> improved,{" "}
                <strong>{comparison.worsened}</strong> worsened, {comparison.unchanged} unchanged, {comparison.entered} new,{" "}
                {comparison.left} gone.
              </p>
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
                    .filter((m) => m.tier_delta !== 0 || (m.score_delta ?? 0) !== 0)
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
                        <td className="muted">{movement.drivers.join(", ") || "no single criterion moved much"}</td>
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
              <h3>Every automated choice, with the basis for it</h3>
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
                <button onClick={() => setConfirmingPublish(true)}>Publish to stewardship and index…</button>
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
              </ConfirmDecision>
            )}
            {published && (
              <p className="status-text" role="status">
                Published {published.rows.length} entities (matched on <code>{published.id_column}</code>) as{" "}
                <code>decision.{published.framework_id}</code>. Next: <a href="#/stewardship/selection">use the tiers in coverage rules</a> or{" "}
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
