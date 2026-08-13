import { useEffect, useState } from "react";
import { BallotReview } from "../components/BallotReview";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { api } from "../api/client";
import type { RunManifest } from "../types";

export function VotingRuns() {
  const [universePath, setUniversePath] = useState<string | null>(null);
  const [companyCount, setCompanyCount] = useState(0);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  async function loadRuns() {
    const res = (await api.listRuns("proxy_voting")) as { runs: RunManifest[] };
    setRuns(res.runs);
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
      setSelectedRunId(res.run_id);
      await loadRuns();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="page">
      <h2>Proxy Voting</h2>
      <p className="help-text">
        Proposal Analysis Agent extracts each company's ballot from its proxy statement; the Policy Application Agent
        recommends a vote (a deterministic house rule, or an LLM judgment call) and cross-checks it against open
        engagement issues. Every proposal requires an explicit human decision before it can be cast.
      </p>

      <section className="card">
        <h3>Start a voting run</h3>
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
        {error && <p className="error-text">{error}</p>}
      </section>

      <section className="card">
        <div className="section-heading">
          <h3>Runs</h3>
          <button className="link-button" onClick={loadRuns}>
            Refresh
          </button>
        </div>
        {runs.length === 0 && <p className="muted">No voting runs yet.</p>}
        {runs.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Awaiting decision</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} className="clickable-row" onClick={() => setSelectedRunId(r.run_id)}>
                  <td>{r.run_id}</td>
                  <td>
                    <span className={`status-pill status-${r.status}`}>{r.status}</span>
                  </td>
                  <td>
                    {r.completed_count}/{r.company_count}
                  </td>
                  <td>{r.review_count}</td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td>
                    <button className="link-button" onClick={(e) => { e.stopPropagation(); setSelectedRunId(r.run_id); }}>
                      Open
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {selectedRunId && (
        <>
          <section className="card">
            <RunProgress runId={selectedRunId} runType="proxy_voting" />
          </section>
          <BallotReview runId={selectedRunId} />
        </>
      )}
    </div>
  );
}
