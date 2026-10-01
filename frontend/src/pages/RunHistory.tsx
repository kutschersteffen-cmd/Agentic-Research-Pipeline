import { RUN_TYPE_LABEL, runTypeLabel, when } from "../lib/runs";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ReviewableRunKind, RunManifest } from "../types";

const REVIEWABLE_KINDS = new Set<ReviewableRunKind>(["theme", "extraction", "financials", "identity", "transition_plan", "tnfd"]);

function isReviewable(runType: string): runType is ReviewableRunKind {
  return REVIEWABLE_KINDS.has(runType as ReviewableRunKind);
}

interface Props {
  onOpenReview?: (kind: ReviewableRunKind, runId: string) => void;
}

export function RunHistory({ onOpenReview }: Props = {}) {
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const res = (await api.listRuns(filter || undefined)) as { runs: RunManifest[] };
      setRuns(res.runs);
    } catch (err) {
      setError(`Runs could not be loaded: ${(err as Error).message}.`);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const totalCost = runs.reduce((sum, r) => sum + r.estimated_cost_usd, 0);

  return (
    <div className="page">
      <h1>Run History</h1>
      <div className="toolbar">
        <label className="field-label inline-label">
          Show
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All run types</option>
            {Object.entries(RUN_TYPE_LABEL).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button className="secondary" onClick={load}>
          Refresh
        </button>
        <span className="muted">
          {runs.length} runs · estimated spend <span className="mono">${totalCost.toFixed(2)}</span>
        </span>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}

      <section className="card">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Type</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Awaiting decision</th>
                <th>Cost</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const runType = r.run_type;
                return (
                  <tr key={r.run_id}>
                    <td className="mono">{r.run_id}</td>
                    <td>{runTypeLabel(runType)}</td>
                    <td>
                      <span className={`status-pill status-${r.status}`}>{r.status}</span>
                      {r.error && <div className="run-error">{r.error}</div>}
                    </td>
                    <td className="mono">
                      {r.completed_count}/{r.company_count}
                      {r.failed_count > 0 && <span className="muted"> · {r.failed_count} companies failed</span>}
                    </td>
                    <td className={r.review_count > 0 ? "mono await-text" : "mono"}>{r.review_count}</td>
                    <td>${r.estimated_cost_usd.toFixed(2)}</td>
                    <td className="mono">{when(r.created_at)}</td>
                    <td>
                      <a href={api.exportRunCsvUrl(r.run_id)} target="_blank" rel="noreferrer">
                        CSV
                      </a>
                      {runType === "proxy_voting" && (
                        <>
                          {" "}
                          <a href={`#/voting/${encodeURIComponent(r.run_id)}`}>Ballot</a>
                        </>
                      )}
                      {r.review_count > 0 && isReviewable(runType) && onOpenReview && (
                        <>
                          {" "}
                          <button className="link-button" onClick={() => onOpenReview(runType, r.run_id)}>
                            Review
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
