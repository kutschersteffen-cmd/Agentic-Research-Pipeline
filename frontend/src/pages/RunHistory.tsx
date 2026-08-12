import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RunManifest } from "../types";

export function RunHistory() {
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [filter, setFilter] = useState<string>("");

  async function load() {
    const res = (await api.listRuns(filter || undefined)) as { runs: RunManifest[] };
    setRuns(res.runs);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const totalCost = runs.reduce((sum, r) => sum + r.estimated_cost_usd, 0);

  return (
    <div className="page">
      <h2>Run History</h2>
      <section className="card">
        <label className="field-label">Filter by type</label>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All</option>
          <option value="theme">Thematic universe</option>
          <option value="extraction">Extraction</option>
          <option value="discovery">Discovery</option>
        </select>
        <button onClick={load}>Refresh</button>
        <p className="muted">Total estimated spend across {runs.length} runs: ${totalCost.toFixed(2)}</p>
      </section>

      <section className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Type</th>
              <th>Status</th>
              <th>Progress</th>
              <th>Flagged</th>
              <th>Cost</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id}>
                <td>{r.run_id}</td>
                <td>{r.run_type}</td>
                <td><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                <td>{r.completed_count}/{r.company_count} ({r.failed_count} failed)</td>
                <td>{r.review_count}</td>
                <td>${r.estimated_cost_usd.toFixed(2)}</td>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td>
                  <a href={api.exportRunCsvUrl(r.run_id)} target="_blank" rel="noreferrer">
                    CSV
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
