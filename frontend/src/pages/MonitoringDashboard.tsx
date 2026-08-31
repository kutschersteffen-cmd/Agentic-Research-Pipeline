import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { EngagementRecord, RunManifest } from "../types";

const ACTIVE_STATUSES = new Set(["running", "pending"]);
const RUN_TYPE_LABEL: Record<string, string> = {
  theme: "Thematic universe",
  extraction: "Data extraction",
  discovery: "Document discovery",
  proxy_voting: "Proxy voting",
  transition_plan: "Transition plan assessment",
  taxonomy_research: "Taxonomy Researcher",
  calibration: "Calibration Agent",
};

function runTypeLabel(runType: string): string {
  return RUN_TYPE_LABEL[runType] ?? runType;
}

export function MonitoringDashboard({ onNavigate }: { onNavigate: (tab: "engagement" | "voting") => void }) {
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [records, setRecords] = useState<EngagementRecord[]>([]);
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

  async function loadRecords() {
    try {
      const res = (await api.listEngagementRecords()) as { records: EngagementRecord[] };
      if (!cancelledRef.current) setRecords(res.records);
    } catch {
      /* engagement store may simply be empty/unreachable -- dashboard degrades gracefully */
    }
  }

  useEffect(() => {
    cancelledRef.current = false;
    loadRecords();

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

  const allIssues = records.flatMap((r) => r.issues.map((issue) => ({ record: r, issue })));
  const openIssues = allIssues.filter((x) => x.issue.status === "open" || x.issue.status === "stalled");
  const stalledIssues = allIssues.filter((x) => x.issue.status === "stalled");
  const escalatedIssues = allIssues.filter((x) => x.issue.escalation_stage !== "private_engagement" && x.issue.status !== "resolved" && x.issue.status !== "closed");

  const votingRuns = runs.filter((r) => r.run_type === "proxy_voting");
  const pendingVoteReviews = votingRuns.reduce((sum, r) => sum + r.review_count, 0);

  return (
    <div className="page">
      <h2>Monitoring Dashboard</h2>
      <p className="help-text">
        A live view across everything the system is doing: batch pipeline runs (thematic universe, extraction,
        discovery, proxy voting) and the stewardship module's open engagement issues. Pipeline runs poll every 3s
        while this page is open.
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
          <div className="stat-tile">
            <span className="stat-value">{openIssues.length}</span>
            <span className="stat-label">Open engagement issues</span>
          </div>
          <div className="stat-tile">
            <span className="stat-value">{stalledIssues.length}</span>
            <span className="stat-label">Stalled (SLA breach)</span>
          </div>
          <div className="stat-tile">
            <span className="stat-value">{escalatedIssues.length}</span>
            <span className="stat-label">Escalated beyond private engagement</span>
          </div>
          <div className="stat-tile">
            <span className="stat-value">{pendingVoteReviews}</span>
            <span className="stat-label">Ballot items awaiting decision</span>
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

      <section className="card">
        <div className="section-heading">
          <h3>Open engagement issues</h3>
          <button className="link-button" onClick={() => onNavigate("engagement")}>
            Open Engagement &rarr;
          </button>
        </div>
        {openIssues.length === 0 && <p className="muted">No open issues.</p>}
        {openIssues.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Company</th>
                <th>Theme</th>
                <th>Status</th>
                <th>Milestone</th>
                <th>Escalation</th>
                <th>Severity</th>
              </tr>
            </thead>
            <tbody>
              {openIssues.slice(0, 30).map(({ record, issue }) => (
                <tr key={issue.issue_id}>
                  <td>{record.name} <span className="muted">({record.company_id})</span></td>
                  <td>{issue.theme}</td>
                  <td><span className={`status-pill status-${issue.status === "stalled" ? "failed" : "running"}`}>{issue.status}</span></td>
                  <td>{issue.milestone_stage.replace(/_/g, " ")}</td>
                  <td>{issue.escalation_stage.replace(/_/g, " ")}</td>
                  <td>{issue.severity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {votingRuns.length > 0 && (
        <section className="card">
          <div className="section-heading">
            <h3>Proxy voting runs</h3>
            <button className="link-button" onClick={() => onNavigate("voting")}>
              Open Voting &rarr;
            </button>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Status</th>
                <th>Companies</th>
                <th>Awaiting decision</th>
              </tr>
            </thead>
            <tbody>
              {votingRuns.map((r) => (
                <tr key={r.run_id}>
                  <td>{r.run_id}</td>
                  <td><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                  <td>{r.completed_count}/{r.company_count}</td>
                  <td>{r.review_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
