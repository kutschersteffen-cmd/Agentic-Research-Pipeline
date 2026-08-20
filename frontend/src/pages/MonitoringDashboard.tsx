import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { RunManifest } from "../types";

const ACTIVE_STATUSES = new Set(["running", "pending"]);
const RUN_TYPE_LABEL: Record<string, string> = {
  theme: "Thematic universe",
  extraction: "Data extraction",
  discovery: "Document discovery",
};

function runTypeLabel(runType: string): string {
  return RUN_TYPE_LABEL[runType] ?? runType;
}

export function MonitoringDashboard() {
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const timerRef = useRef<number | undefined>(undefined);
  const cancelledRef = useRef(false);

  async function loadRuns() {
    try {
      const res = (await api.listRuns()) as { runs: RunManifest[] };
      if (cancelledRef.current) return;
      setRuns(res.runs);
      setLoadError(null);
    } catch (err) {
      if (!cancelledRef.current) setLoadError((err as Error).message);
    }
  }

  useEffect(() => {
    cancelledRef.current = false;

    async function tick() {
      await loadRuns();
      if (cancelledRef.current) return;
      timerRef.current = window.setTimeout(tick, 3000);
    }
    tick();

    return () => {
      cancelledRef.current = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const active = runs.filter((r) => ACTIVE_STATUSES.has(r.status));
  const finished = runs
    .filter((r) => !ACTIVE_STATUSES.has(r.status))
    .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))
    .slice(0, 25);

  return (
    <div className="page">
      <h2>Monitoring Dashboard</h2>
      <p className="help-text">
        A live view across everything the system is doing: batch pipeline runs (thematic universe, extraction,
        discovery). Pipeline runs poll every 3s while this page is open.
      </p>
      {loadError && <p className="error-text">Failed to refresh runs: {loadError}</p>}

      <section className="card">
        <div className="dashboard-grid">
          <div className="stat-tile">
            <span className="stat-value">{active.length}</span>
            <span className="stat-label">Currently executing</span>
          </div>
          <div className="stat-tile">
            <span className="stat-value">{finished.length}</span>
            <span className="stat-label">Finished runs (recent)</span>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="section-heading">
          <h3>Currently executing</h3>
        </div>
        {active.length === 0 && <p className="muted">Nothing running right now.</p>}
        {active.map((r) => {
          const pct = r.company_count > 0 ? Math.round((r.completed_count / r.company_count) * 100) : 0;
          return (
            <div className="activity-row" key={r.run_id}>
              <div className="activity-main">
                <div className="run-progress-header">
                  <strong>{r.run_id}</strong>
                  <span className={`status-pill status-${r.status}`}>{r.status}</span>
                </div>
                <div className="progress-bar">
                  <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
                </div>
                <div className="activity-meta">
                  <span>{runTypeLabel(r.run_type)}</span>
                  <span>{r.completed_count}/{r.company_count} companies</span>
                  <span>{r.failed_count} failed</span>
                  <span>{r.review_count} flagged</span>
                  <span>${r.estimated_cost_usd.toFixed(2)}</span>
                </div>
              </div>
            </div>
          );
        })}
      </section>

      <section className="card">
        <div className="section-heading">
          <h3>Finished runs</h3>
          <span className="muted">most recent 25</span>
        </div>
        {finished.length === 0 && <p className="muted">No finished runs yet.</p>}
        {finished.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Type</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Flagged</th>
                <th>Finished</th>
              </tr>
            </thead>
            <tbody>
              {finished.map((r) => (
                <tr key={r.run_id}>
                  <td>{r.run_id}</td>
                  <td>{runTypeLabel(r.run_type)}</td>
                  <td><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                  <td>{r.completed_count}/{r.company_count} ({r.failed_count} failed)</td>
                  <td>{r.review_count}</td>
                  <td>{new Date(r.updated_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
