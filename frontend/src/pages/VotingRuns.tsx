import { when } from "../lib/runs";
import { useEffect, useState } from "react";
import { BallotReview } from "../components/BallotReview";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { api } from "../api/client";
import type { RunManifest } from "../types";
import { activatable } from "../lib/activatable";

/** The open run lives in the URL (`#/voting/<run id>`), so a link to a
 * pending ballot opens straight onto it. */
export function VotingRuns({ selectedRunId, onSelectRun }: { selectedRunId: string | null; onSelectRun: (runId: string) => void }) {
  const [universePath, setUniversePath] = useState<string | null>(null);
  const [companyCount, setCompanyCount] = useState(0);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [runs, setRuns] = useState<RunManifest[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);

  async function loadRuns() {
    try {
      const res = (await api.listRuns("proxy_voting")) as { runs: RunManifest[] };
      setRuns(res.runs);
      setRunsError(null);
    } catch (err) {
      setRunsError((err as Error).message);
    }
  }

  useEffect(() => {
    loadRuns();
  }, []);

  async function startRun() {
    if (!universePath) return;
    setStarting(true);
    setError(null);
    try {
      const res = await api.startVotingRun({ universe_path: universePath });
      onSelectRun(res.run_id);
      await loadRuns();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="page">
      <h1>Proxy Voting</h1>
      <p className="help-text">Agents read each proxy statement and recommend a vote under house policy, checked against open engagement issues. Nothing is cast until a named person decides every proposal.</p>

      {selectedRunId && (
        <>
          <BallotReview runId={selectedRunId} />
          <section className="card">
            <RunProgress runId={selectedRunId} runType="proxy_voting" />
          </section>
        </>
      )}

      <section className="card">
        <div className="section-heading">
          <h2>Runs</h2>
          <button className="link-button" onClick={loadRuns}>
            Refresh
          </button>
        </div>
        {runsError && (
          <p className="error-text" role="alert">
            Voting runs could not be loaded: {runsError}.{" "}
            <button className="link-button" onClick={loadRuns}>
              Retry
            </button>
          </p>
        )}
        {runs === null && !runsError && <p className="muted" aria-live="polite">Loading runs…</p>}
        {runs?.length === 0 && <p className="muted">No voting runs yet. Start one below.</p>}
        {runs && runs.length > 0 && (
          <div className="table-wrap">
            <table className="data-table stack-on-phone">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Awaiting decision</th>
                  <th>Updated</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.run_id} className="clickable-row" {...activatable(() => onSelectRun(r.run_id))} aria-current={r.run_id === selectedRunId || undefined}>
                    <td data-label="Run" className="mono">{r.run_id}</td>
                    <td data-label="Status">
                      <span className={`status-pill status-${r.status}`}>{r.status}</span>
                    </td>
                    <td data-label="Progress" className="mono">
                      {r.completed_count}/{r.company_count}
                    </td>
                    <td data-label="Awaiting decision" className={r.review_count > 0 ? "await-text" : undefined}>{r.review_count}</td>
                    <td data-label="Updated" className="mono">{when(r.updated_at)}</td>
                    <td>
                      <a href={`#/voting/${encodeURIComponent(r.run_id)}`} onClick={(e) => e.stopPropagation()}>
                        Open
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Once a run is open the ballots are the work; starting another run
          folds away below them. */}
      <details className="card start-run" open={!selectedRunId}>
        <summary>
          <h2>Start a voting run</h2>
        </summary>
        <UniversePicker
          onResolved={(path, count) => {
            setUniversePath(path);
            setCompanyCount(count);
          }}
        />
        {universePath && (
          <p className="status-text">
            {companyCount} companies loaded from {universePath}
          </p>
        )}
        <button onClick={startRun} disabled={starting || !universePath}>
          Run proposal analysis &amp; policy application
        </button>
        {error && <p className="error-text" role="alert">{error}</p>}
      </details>
    </div>
  );
}
