import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { RunDecision, RunScoringKind, TemplateMatch } from "../types";

interface PickerProps {
  runType: RunScoringKind;
  /** Extraction only: the schema's field names, which become the table's columns. */
  fieldNames?: string[];
  value: string | null;
  onChange: (frameworkId: string | null) => void;
}

/** Choose a Decision Studio framework to score a run's results with. Every
 * saved framework is listed, fitting ones first; one that needs columns this
 * run will not produce is shown with the gap and cannot be picked. */
export function ScoringTemplatePicker({ runType, fieldNames, value, onChange }: PickerProps) {
  const [matches, setMatches] = useState<TemplateMatch[] | null>(null);
  const [error, setError] = useState("");
  const fieldKey = (fieldNames ?? []).join("\u0000");

  useEffect(() => {
    let live = true;
    api
      .matchTemplates({ run_type: runType, field_names: fieldKey ? fieldKey.split("\u0000") : [] })
      .then((m) => live && setMatches(m))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [runType, fieldKey]);

  const selected = matches?.find((m) => m.config.framework_id === value);
  // A schema edit can turn a picked template into a misfit; drop it rather than send a run the server will refuse.
  useEffect(() => {
    if (selected && selected.missing_columns.length > 0) onChange(null);
  }, [selected, onChange]);

  if (error) return <p className="error-text">{error}</p>;
  if (!matches) return <p className="status-text">Loading scoring templates…</p>;
  if (matches.length === 0) {
    return <p className="help-text">No scoring templates saved yet. Build one in Decision Studio from an earlier run, then pick it here.</p>;
  }

  return (
    <div>
      <label className="field-label">
        Scoring template (optional)
        <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">No scoring — results only</option>
          {matches.map((m) => (
            <option key={m.config.framework_id} value={m.config.framework_id} disabled={m.missing_columns.length > 0}>
              {m.config.name} v{m.config.version}
              {m.config.ratified ? " (ratified)" : " (draft)"}
              {m.missing_columns.length > 0 ? ` — needs ${m.missing_columns.join(", ")}` : ""}
            </option>
          ))}
        </select>
      </label>
      {selected && (
        <p className="help-text">
          Scores on {selected.required_columns.length} columns with {selected.config.criteria.filter((c) => c.enabled).length}{" "}
          criteria into {selected.config.tiers.length} tiers. The run is pinned to v{selected.config.version}, so later edits to the
          template do not change how this run is scored.
        </p>
      )}
    </div>
  );
}

interface PanelProps {
  runId: string;
  runType: RunScoringKind;
  fieldNames?: string[];
}

/** The run's results scored with its pinned template, or a picker to attach one. */
export function RunScoringPanel({ runId, runType, fieldNames }: PanelProps) {
  const [decision, setDecision] = useState<RunDecision | null>(null);
  const [unattached, setUnattached] = useState(false);
  const [choice, setChoice] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setDecision(await api.getRunDecision(runId));
      setUnattached(false);
    } catch (e) {
      const message = (e as Error).message;
      if (message.includes("No scoring template")) setUnattached(true);
      else setError(message);
    }
  }, [runId]);

  useEffect(() => {
    load();
  }, [load]);

  async function attach() {
    if (!choice) return;
    try {
      await api.attachRunFramework(runId, choice);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="card">
      <div className="toolbar">
        <h3>Scoring</h3>
        {decision && (
          <button className="link-button" onClick={load}>
            Re-score
          </button>
        )}
      </div>
      {error && <p className="error-text">{error}</p>}

      {unattached && (
        <>
          <ScoringTemplatePicker runType={runType} fieldNames={fieldNames} value={choice} onChange={setChoice} />
          <button onClick={attach} disabled={!choice}>
            Score this run
          </button>
        </>
      )}

      {decision && (
        <>
          <p className="help-text">
            {decision.framework.name} v{decision.framework.version}
            {decision.run_status === "running" ? " — the run is still going, so this scores the companies finished so far." : "."}
          </p>
          {decision.missing_columns.length > 0 && (
            <p className="decision-check-banner">
              These columns are missing from the results, so the criteria on them were skipped: {decision.missing_columns.join(", ")}
            </p>
          )}
          <div className="decision-kpis">
            {decision.result.tier_summary.map((tier) => (
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
                {decision.result.excluded_count} / {decision.result.insufficient_count}
              </p>
            </div>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Company</th>
                <th>Score</th>
                <th>Tier</th>
                <th>Action</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {[...decision.result.entities]
                .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.name.localeCompare(b.name))
                .map((entity) => (
                  <tr key={entity.entity_key}>
                    <td>{entity.rank ?? "—"}</td>
                    <td>{entity.name}</td>
                    <td>{entity.score != null ? entity.score.toFixed(1) : "—"}</td>
                    <td>{entity.tier_name ?? entity.status}</td>
                    <td>{entity.tier_action ?? ""}</td>
                    <td className="muted">{entity.notes.join("; ")}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
