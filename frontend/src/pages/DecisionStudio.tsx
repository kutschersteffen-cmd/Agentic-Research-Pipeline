import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { AuditLogView } from "../components/AuditLogView";
import { ColumnProfileTable } from "../components/ColumnProfileTable";
import { DecisionResultsTable } from "../components/DecisionResultsTable";
import { DecisionTreeEditor } from "../components/DecisionTreeEditor";
import { MechanismEditor } from "../components/MechanismEditor";
import { ScoreDistribution } from "../components/ScoreDistribution";
import type {
  ColumnRole,
  DatasetSummary,
  DecisionComparison,
  DecisionResult,
  Direction,
  EntityDecision,
  EntitySensitivity,
  MechanismConfig,
  AuditEntry,
} from "../types";
import { Button, StateBlock } from "../ui";

const SUB_TABS = [
  { id: "data", label: "1 · Data" },
  { id: "profile", label: "2 · Profile" },
  { id: "mechanism", label: "3 · Mechanism" },
  { id: "tree", label: "4 · Decision tree" },
  { id: "results", label: "5 · Results" },
  { id: "movement", label: "6 · Movement" },
  { id: "audit", label: "7 · Audit" },
] as const;

// `entity` names what one row of the resulting table actually is. Three of
// these are not companies, which is the point: the engine scores rows.
const SOURCES = [
  { id: "transition_plan_run", label: "Transition plan run", entity: "company", needsRun: true, needsRegion: false },
  { id: "extraction_run", label: "Extraction run", entity: "company", needsRun: true, needsRegion: false },
  { id: "theme_run", label: "Thematic universe run", entity: "company", needsRun: true, needsRegion: false },
  { id: "portfolio_snapshot", label: "Portfolio snapshot + climate", entity: "company", needsRun: false, needsRegion: false },
  { id: "transition_barrier", label: "Transition barrier matrix", entity: "sector × region", needsRun: false, needsRegion: true },
  { id: "emerging_themes_run", label: "Emerging themes run", entity: "theme", needsRun: true, needsRegion: false },
  { id: "replication_runs", label: "Strategy replication runs", entity: "strategy", needsRun: false, needsRegion: false },
] as const;

const BARRIER_REGIONS = ["", "European Union", "United States", "China"];

export function DecisionStudio() {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>("data");
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [dataset, setDataset] = useState<DatasetSummary | null>(null);
  const [config, setConfig] = useState<MechanismConfig | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [result, setResult] = useState<DecisionResult | null>(null);
  const [comparison, setComparison] = useState<DecisionComparison | null>(null);
  const [sensitivity, setSensitivity] = useState<EntitySensitivity | null>(null);
  const [orderBy, setOrderBy] = useState<"score" | "leverage">("score");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [source, setSource] = useState<string>("transition_plan_run");
  const [runId, setRunId] = useState("");
  const [region, setRegion] = useState("");
  const [compareWith, setCompareWith] = useState("");
  const [baseVersion, setBaseVersion] = useState<number | null>(null);
  const scoreTimer = useRef<number | undefined>(undefined);

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
    const summary = await guard("Parsing and profiling…", () => api.uploadDecisionDataset(file));
    if (summary) {
      selectDataset(summary);
      refreshDatasets();
    }
  }

  async function onFromSource() {
    const summary = await guard("Building the table…", () =>
      api.decisionDatasetFromSource({ source, run_id: runId || undefined, region: region || undefined }),
    );
    if (summary) {
      selectDataset(summary);
      refreshDatasets();
    }
  }

  function selectDataset(summary: DatasetSummary) {
    setDataset(summary);
    setConfig(null);
    setResult(null);
    setAudit([]);
    setComparison(null);
    setBaseVersion(null);
    setSub("profile");
  }

  async function onDerive() {
    if (!dataset) return;
    const envelope = await guard("Deriving the mechanism…", () =>
      api.deriveMechanism({ dataset_id: dataset.dataset_id, name: `Framework for ${dataset.name}`, save: true }),
    );
    if (envelope) {
      setConfig(envelope.config);
      setAudit(envelope.audit);
      // v1 is the proposal as derived. Saving it now is what lets the next
      // save diff against it and record which rules a person changed.
      setBaseVersion(envelope.config.version);
      setSub("mechanism");
    }
  }

  // Every number on this page comes back from the engine. Editing a rule
  // re-scores server-side rather than recomputing anything locally, so what
  // is on screen is exactly what the audit trail records.
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
  }, [dataset, config]);

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
    const proposal = dataset?.proposals.find((p) => p.column === column);
    if (role === "criterion") {
      next.criteria = [
        ...next.criteria,
        {
          column,
          dimension_id: config.dimensions[0]?.id ?? "d0",
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
      setConfig(envelope.config);
      setAudit(envelope.audit);
      setBaseVersion(envelope.config.version);
    }
  }

  async function onRatify() {
    if (!config) return;
    const saved = await guard("Ratifying…", () => api.ratifyMechanism(config.framework_id, config.version));
    if (saved) setConfig(saved);
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
      <h2>Decision Studio</h2>
      <p className="help-text">
        Turns any per-entity table this system produces into a scored, ranked and tiered decision — deterministically,
        with no LLM anywhere in the numbers, and with every automated choice and every edit of yours recorded. See{" "}
        <code>docs/DECISION_MECHANISM.md</code> for the design.
      </p>

      <nav className="sub-nav">
        {SUB_TABS.map((tab) => (
          <button
            key={tab.id}
            className={tab.id === sub ? "nav-tab active" : "nav-tab"}
            onClick={() => setSub(tab.id)}
            disabled={tab.id !== "data" && !dataset}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {status && <p className="status-text">{status}</p>}
      {error && <StateBlock kind="error" message={error} />}

      {dataset && (
        <div className="toolbar decision-context">
          <span>
            <strong>{dataset.name}</strong> — {dataset.row_count} rows, {dataset.columns.length} columns
          </span>
          {dataset.has_confidence && <span className="badge badge-high">carries per-cell confidence</span>}
          {config && (
            <span className="muted">
              {config.name} v{config.version} {config.ratified ? "(ratified)" : "(draft)"}
            </span>
          )}
          {!config && (
            <Button variant="ghost" onClick={onDerive}>
              Derive a mechanism
            </Button>
          )}
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
          <input type="file" accept=".csv,.tsv,.txt,.xlsx,.xls" onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])} />

          <h3>…or build it from a run this system already produced</h3>
          <div className="inline-fields">
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              {SOURCES.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
            {SOURCES.find((s) => s.id === source)?.needsRun && (
              <input placeholder="run id" value={runId} onChange={(e) => setRunId(e.target.value)} />
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
            <Button variant="ghost" onClick={onFromSource}>
              Build table
            </Button>
          </div>
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
                    <tr key={d.dataset_id} className="clickable-row" onClick={() => selectDataset(d)}>
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
              profiles={dataset.profiles}
              proposals={dataset.proposals}
              config={config}
              onSetRole={setRole}
              onSetDirection={setDirection}
            />
          ) : (
            <p className="muted">Derive a mechanism to edit roles and directions.</p>
          )}
        </div>
      )}

      {sub === "mechanism" && dataset && config && (
        <MechanismEditor config={config} profiles={dataset.profiles} weights={result?.effective_weights ?? {}} onChange={setConfig} />
      )}

      {sub === "tree" && dataset && config && (
        <DecisionTreeEditor config={config} profiles={dataset.profiles} result={result} onChange={setConfig} />
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
              <Button variant="ghost" onClick={onExport}>
                Export CSV
              </Button>
            </div>
            <DecisionResultsTable result={result} config={config} orderBy={orderBy} onOrderBy={setOrderBy} onExplain={onExplain} />
          </div>

          {sensitivity && (
            <div className="card">
              <div className="toolbar">
                <h3>How much do the weights matter — {sensitivity.name}</h3>
                <Button variant="ghost" onClick={() => setSensitivity(null)}>
                  Close
                </Button>
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
            <Button variant="ghost" onClick={onCompare} disabled={!compareWith}>
              Compare
            </Button>
          </div>

          {comparison && (
            <>
              {!comparison.comparable && <StateBlock kind="error" message={comparison.incomparable_reason} />}
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
              <Button variant="ghost" onClick={onSave}>
                Save as new version
              </Button>
              <Button variant="ghost" onClick={onRatify} disabled={config.ratified}>
                {config.ratified ? "Ratified" : "Ratify this version"}
              </Button>
            </div>
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
