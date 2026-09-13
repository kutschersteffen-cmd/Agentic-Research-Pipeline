import { useEffect, useState } from "react";
import { api } from "../api/client";
import { AggregationView, TrendView } from "../components/ResultView";
import { PivotTable } from "../components/PivotTable";
import type { DashboardSpec, GeneratedDashboard, Narrative, PanelResult } from "../types";

const EXAMPLE_BRIEFS = [
  "Give me a climate risk overview of the sustainable leaders fund",
  "Where is our equity exposure concentrated, and how has it moved?",
  "Compare carbon intensity across portfolios and show me where the data is thin",
];

/** Panels describe their own query in the same vocabulary the Explore and
 * Pivot tabs use, so a generated panel is always reproducible by hand --
 * the point of showing it is that nothing about the number is opaque. */
function queryLine(panel: PanelResult["panel"]): string {
  const parts: string[] = [`kind=${panel.kind}`, `metric=${panel.metric}`];
  if (panel.kind === "pivot") parts.push(`rows=${panel.row_dim}`, `cols=${panel.col_dim}`);
  else parts.push(`group_by=${panel.group_by}`);
  if (panel.data_point_field_id) parts.push(`field=${panel.data_point_field_id}`);
  if (Object.keys(panel.security_filter).length > 0) parts.push(`filter=${JSON.stringify(panel.security_filter)}`);
  parts.push(`portfolios=${panel.portfolio_filter.length > 0 ? panel.portfolio_filter.join(", ") : "all"}`);
  if (panel.date_range) parts.push(`range=${panel.date_range[0]}..${panel.date_range[1]}`);
  else if (panel.as_of) parts.push(`as_of=${panel.as_of}`);
  return parts.join(", ");
}

function NarrativeBlock({ narrative }: { narrative?: Narrative }) {
  if (!narrative || !narrative.text) return null;
  return (
    <>
      <p className="answer-text">{narrative.text}</p>
      {narrative.source === "llm" ? (
        <p className="muted">
          <span className="badge badge-low">figures checked</span> Every figure in this text was matched back to a computed panel
          result.
        </p>
      ) : narrative.ungrounded_tokens.length > 0 ? (
        <div className="banner banner-warning">
          Generated commentary was rejected: it stated {narrative.ungrounded_tokens.join(", ")}, which no panel computed. The
          deterministically computed figures are shown instead.
          <details>
            <summary>Rejected draft</summary>
            <p className="muted">{narrative.rejected_draft}</p>
          </details>
        </div>
      ) : (
        <p className="muted">Computed figures, stated as-is -- no commentary was generated for this panel.</p>
      )}
    </>
  );
}

function PanelCard({ panel, narrative }: { panel: PanelResult; narrative?: Narrative }) {
  const unit = panel.facts.find((f) => f.unit && f.unit !== "EUR" && f.unit !== "share")?.unit;

  return (
    <section className="card">
      <h4>{panel.panel.title}</h4>
      {panel.panel.question && <p className="help-text">{panel.panel.question}</p>}
      {panel.error ? (
        <div className="banner banner-danger">This panel could not be computed: {panel.error}</div>
      ) : (
        <>
          <NarrativeBlock narrative={narrative} />
          {panel.facts.length > 0 && (
            <ul className="citation-list">
              {panel.facts.map((fact) => (
                <li key={fact.fact_id}>{fact.text}</li>
              ))}
            </ul>
          )}
          {panel.aggregation && <AggregationView result={panel.aggregation} unit={unit} />}
          {panel.trend && panel.trend.length > 0 && <TrendView trend={panel.trend} unit={unit} />}
          {panel.pivot && <PivotTable result={panel.pivot} />}
        </>
      )}
      <p className="muted">Query: {queryLine(panel.panel)}</p>
    </section>
  );
}

function DashboardView({
  dashboard,
  onSave,
  onRerun,
  saving,
}: {
  dashboard: GeneratedDashboard;
  onSave?: () => void;
  onRerun?: (asOf: string) => void;
  saving?: boolean;
}) {
  const [asOf, setAsOf] = useState("");
  const snapshotDates = Array.from(new Set(dashboard.panels.map((p) => p.as_of).filter(Boolean)));

  if (dashboard.clarification_needed) {
    return (
      <section className="card">
        <div className="banner banner-warning">
          No dashboard was planned: {dashboard.clarification_needed} Nothing was invented in its place -- refine the brief and
          try again.
        </div>
        {dashboard.warnings.map((w) => (
          <p key={w} className="muted">
            {w}
          </p>
        ))}
      </section>
    );
  }

  return (
    <>
      <section className="card">
        <h3>{dashboard.spec.title}</h3>
        {dashboard.spec.goal && <p className="help-text">{dashboard.spec.goal}</p>}
        <NarrativeBlock narrative={dashboard.headline} />
        <div className="chip-row">
          <span className="chip">{dashboard.panels.length} panel(s)</span>
          <span className="chip">as of {dashboard.as_of || "n/a"}</span>
          {snapshotDates.length > 1 && <span className="chip">snapshots: {snapshotDates.join(", ")}</span>}
        </div>
        <div className="toolbar">
          {onSave && (
            <button onClick={onSave} disabled={saving}>
              {saving ? "Saving..." : "Save dashboard"}
            </button>
          )}
          {onRerun && (
            <>
              <select value={asOf} onChange={(e) => setAsOf(e.target.value)}>
                <option value="">latest snapshot</option>
                {snapshotDates.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
              <button onClick={() => onRerun(asOf)}>Re-run (no LLM)</button>
            </>
          )}
        </div>
        {dashboard.warnings.length > 0 && (
          <details>
            <summary>{dashboard.warnings.length} planner/execution warning(s)</summary>
            <ul className="citation-list">
              {dashboard.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </details>
        )}
        <details>
          <summary>Dashboard spec (the re-runnable definition)</summary>
          <pre className="review-json">{JSON.stringify(dashboard.spec, null, 2)}</pre>
        </details>
      </section>

      {dashboard.panels.map((panel) => (
        <PanelCard key={panel.panel.panel_id} panel={panel} narrative={dashboard.panel_narratives[panel.panel.panel_id]} />
      ))}
    </>
  );
}

/** Generative BI: a plain-language brief becomes a whole dashboard rather
 * than a single answer. The LLM plans which queries to run and writes the
 * commentary; the deterministic aggregation engine computes every figure,
 * and every figure in the commentary is checked back against those
 * computed results before it is shown. */
export function GenerativeBI() {
  const [brief, setBrief] = useState("");
  const [narrate, setNarrate] = useState(true);
  const [dashboard, setDashboard] = useState<GeneratedDashboard | null>(null);
  const [saved, setSaved] = useState<DashboardSpec[]>([]);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshSaved() {
    try {
      setSaved(await api.listDashboards());
    } catch {
      setSaved([]);
    }
  }

  useEffect(() => {
    refreshSaved();
  }, []);

  async function generate(text: string) {
    setBusy(true);
    setError(null);
    setDashboard(null);
    try {
      setDashboard(await api.generateDashboard(text, { narrate }));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!dashboard) return;
    setSaving(true);
    try {
      await api.saveDashboard(dashboard.spec);
      await refreshSaved();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function rerun(dashboardId: string, asOf: string) {
    setBusy(true);
    setError(null);
    try {
      setDashboard(await api.runDashboard(dashboardId, asOf || undefined));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function rerunCurrent(asOf: string) {
    if (!dashboard) return;
    setBusy(true);
    setError(null);
    try {
      setDashboard(await api.executeDashboardSpec(dashboard.spec, asOf || undefined));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="card">
        <h3>Describe the dashboard you want</h3>
        <p className="help-text">
          The model plans the panels and writes the commentary; it never produces a number. Every figure comes from the same
          deterministic engine the Explore and Pivot tabs use, and every figure in the commentary is matched back to a computed
          panel result before you see it -- an invented or derived figure is rejected and replaced by the computed facts.
          Requires <code>ARP_ANTHROPIC_API_KEY</code> on the server.
        </p>
        <textarea
          rows={3}
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          placeholder="e.g. climate risk overview of the sustainable leaders fund, including where the data is thin"
        />
        <label className="checkbox-label">
          <input type="checkbox" checked={narrate} onChange={(e) => setNarrate(e.target.checked)} />
          Write commentary (uncheck for panels and computed facts only -- one LLM call instead of two)
        </label>
        <div className="toolbar">
          <button onClick={() => generate(brief)} disabled={busy || !brief.trim()}>
            {busy ? "Generating..." : "Generate dashboard"}
          </button>
          {EXAMPLE_BRIEFS.map((b) => (
            <button
              key={b}
              className="link-button"
              disabled={busy}
              onClick={() => {
                setBrief(b);
                generate(b);
              }}
            >
              {b}
            </button>
          ))}
        </div>
        {error && <p className="error-text">{error}</p>}
      </section>

      {saved.length > 0 && (
        <section className="card">
          <h3>Saved dashboards ({saved.length})</h3>
          <p className="help-text">
            A saved dashboard is a re-runnable definition, not a stored answer: re-running recomputes every panel from current
            holdings with no LLM call at all, so a recurring report can't drift between runs except through the data.
          </p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Panels</th>
                <th>Created</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {saved.map((spec) => (
                <tr key={spec.dashboard_id}>
                  <td>{spec.title}</td>
                  <td>{spec.panels.length}</td>
                  <td>{spec.created_at.slice(0, 10)}</td>
                  <td>
                    <button className="link-button" disabled={busy} onClick={() => rerun(spec.dashboard_id, "")}>
                      Re-run
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {dashboard && <DashboardView dashboard={dashboard} onSave={save} onRerun={rerunCurrent} saving={saving} />}
    </>
  );
}
