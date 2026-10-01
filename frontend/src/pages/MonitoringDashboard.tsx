import { when } from "../lib/runs";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { EngagementRecord, ReviewableRunKind, RunManifest } from "../types";
import { ACTIVE_STATUSES, REVIEWABLE_RUN_TYPES, runTypeLabel } from "../lib/runs";

interface Props {
  onNavigate: (tab: "engagement" | "voting" | "review") => void;
  onOpenReview?: (kind: ReviewableRunKind, runId: string) => void;
}

export function MonitoringDashboard({ onNavigate, onOpenReview }: Props) {
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [records, setRecords] = useState<EngagementRecord[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [recordsError, setRecordsError] = useState<string | null>(null);
  // Null until the first successful poll: a count we never received is
  // unknown, never zero.
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [recordsLoaded, setRecordsLoaded] = useState(false);
  const timerRef = useRef<number | undefined>(undefined);
  const cancelledRef = useRef(false);

  async function loadRuns() {
    try {
      const res = (await api.listRuns()) as { runs: RunManifest[] };
      if (cancelledRef.current) return;
      setRuns(res.runs);
      setLoadError(null);
      setLastRefreshed(new Date());
    } catch (err) {
      if (!cancelledRef.current) setLoadError((err as Error).message);
    }
  }

  async function loadRecords() {
    try {
      const res = (await api.listEngagementRecords()) as { records: EngagementRecord[] };
      if (cancelledRef.current) return;
      setRecords(res.records);
      setRecordsLoaded(true);
      setRecordsError(null);
    } catch (err) {
      if (!cancelledRef.current) setRecordsError((err as Error).message);
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

  // Runs are replaced every 3s by the poll above, so these derive from `runs`;
  // the issue lists derive from `records`, which loads once at mount -- without
  // the memo they were rescanned on every tick for a result that never changed.
  const active = useMemo(() => runs.filter((r) => ACTIVE_STATUSES.has(r.status)), [runs]);
  const finished = useMemo(
    () =>
      runs
        .filter((r) => !ACTIVE_STATUSES.has(r.status))
        .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))
        .slice(0, 25),
    [runs],
  );

  const allIssues = useMemo(
    () => records.flatMap((r) => r.issues.map((issue) => ({ record: r, issue }))),
    [records],
  );
  const openIssues = useMemo(
    () => allIssues.filter((x) => x.issue.status === "open" || x.issue.status === "stalled"),
    [allIssues],
  );
  const stalledIssues = useMemo(() => allIssues.filter((x) => x.issue.status === "stalled"), [allIssues]);
  const escalatedIssues = useMemo(
    () =>
      allIssues.filter(
        (x) => x.issue.escalation_stage !== "private_engagement" && x.issue.status !== "resolved" && x.issue.status !== "closed",
      ),
    [allIssues],
  );

  const votingRuns = useMemo(() => runs.filter((r) => r.run_type === "proxy_voting"), [runs]);

  const runsKnown = lastRefreshed !== null;
  const show = (known: boolean, n: number) => (known ? n : "—");

  return (
    <div className="page">
      <h1>Dashboard</h1>
      <p className="help-text">What needs a decision first, then what the agents are doing. Runs refresh every 3 seconds.</p>
      <div aria-live="polite">
        {loadError && (
          <div className="error-text" role="alert">
            Runs could not be refreshed: {loadError}.{" "}
            {runsKnown ? `Showing data from ${lastRefreshed.toLocaleTimeString()}.` : "Counts are unknown until the backend responds."}{" "}
            <button className="link-button" onClick={loadRuns}>
              Retry now
            </button>
          </div>
        )}
        {recordsError && (
          <div className="error-text" role="alert">
            Engagement issues could not be loaded: {recordsError}.{" "}
            <button className="link-button" onClick={loadRecords}>
              Retry
            </button>
          </div>
        )}
      </div>

      <dl className="dashboard-grid">
        <div className="stat-tile">
          <dt className="stat-label">Escalated beyond private engagement</dt>
          <dd className={recordsLoaded && escalatedIssues.length > 0 ? "stat-value stat-low" : "stat-value"}>{show(recordsLoaded, escalatedIssues.length)}</dd>
        </div>
        <div className="stat-tile">
          <dt className="stat-label">Stalled (SLA breach)</dt>
          <dd className={recordsLoaded && stalledIssues.length > 0 ? "stat-value stat-mid" : "stat-value"}>{show(recordsLoaded, stalledIssues.length)}</dd>
        </div>
        <div className="stat-tile">
          <dt className="stat-label">Open engagement issues</dt>
          <dd className="stat-value">{show(recordsLoaded, openIssues.length)}</dd>
        </div>
        <div className="stat-tile">
          <dt className="stat-label">Runs executing now</dt>
          <dd className="stat-value">{show(runsKnown, active.length)}</dd>
        </div>
      </dl>

      {/* Runs are the primary stream (left); stewardship status supports it
          (right). Stacks to one column below 1180px. */}
      <div className="dashboard-columns">
        <div className="dashboard-column">
          <section className={active.length === 0 ? "card card-empty" : "card"}>
            <div className="section-heading">
              <h2>Currently executing</h2>
              {active.length === 0 && <span className="muted">{runsKnown ? "Nothing running right now." : "Unknown until runs load."}</span>}
            </div>
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
                      <div className="progress-bar-fill" style={{ transform: `scaleX(${pct / 100})` }} />
                    </div>
                    <div className="activity-meta">
                      <span>{runTypeLabel(r.run_type)}</span>
                      <span>{r.completed_count}/{r.company_count} companies</span>
                      {r.failed_count > 0 && <span>{r.failed_count} failed</span>}
                      <span>{r.review_count} awaiting</span>
                      <span>${r.estimated_cost_usd.toFixed(2)}</span>
                      {r.review_count > 0 && REVIEWABLE_RUN_TYPES.has(r.run_type) && onOpenReview && (
                        <button className="link-button" style={{ marginTop: 0 }} onClick={() => onOpenReview(r.run_type as ReviewableRunKind, r.run_id)}>
                          Review {r.review_count} flagged &rarr;
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </section>

          <section className={finished.length === 0 ? "card card-empty" : "card"}>
            <div className="section-heading">
              <h2>Finished runs</h2>
              <span className="muted">{finished.length > 0 ? "Most recent 25" : runsKnown ? "No finished runs yet." : "Unknown until runs load."}</span>
            </div>
            {finished.length > 0 && (
              <div className="table-wrap">
                <table className="data-table stack-on-phone">
                  <thead>
                    <tr>
                      <th>Run ID</th>
                      <th>Type</th>
                      <th>Status</th>
                      <th>Progress</th>
                      <th>Awaiting</th>
                      <th>Finished</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {finished.map((r) => (
                      <tr key={r.run_id}>
                        <td data-label="Run" className="mono">{r.run_id}</td>
                        <td data-label="Type">{runTypeLabel(r.run_type)}</td>
                        <td data-label="Status"><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                        <td data-label="Progress" className="mono">
                          {r.completed_count}/{r.company_count}
                          {r.failed_count > 0 && <span className="muted"> · {r.failed_count} failed</span>}
                        </td>
                        <td data-label="Awaiting" className="mono">{r.review_count}</td>
                        <td data-label="Finished" className="mono">{when(r.updated_at)}</td>
                        <td>
                          {r.run_type === "proxy_voting" && <a href={`#/voting/${encodeURIComponent(r.run_id)}`}>Ballot</a>}
                          {r.review_count > 0 && REVIEWABLE_RUN_TYPES.has(r.run_type) && onOpenReview && (
                            <button className="link-button" style={{ marginTop: 0 }} onClick={() => onOpenReview(r.run_type as ReviewableRunKind, r.run_id)}>
                              Review
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
        <div className="dashboard-column">
          <section className={openIssues.length === 0 ? "card card-empty" : "card"}>
            <div className="section-heading">
              <h2>Open engagement issues</h2>
              {openIssues.length === 0 && <span className="muted">{recordsLoaded ? "No open issues." : "Unknown until issues load."}</span>}
              <button className="link-button" onClick={() => onNavigate("engagement")}>
                Open Engagement &rarr;
              </button>
            </div>
            {openIssues.slice(0, 30).map(({ record, issue }) => (
              <div className="activity-row" key={issue.issue_id}>
                <div className="activity-main">
                  <div className="run-progress-header">
                    <strong>
                      {record.name} <span className="muted">({record.company_id})</span>
                    </strong>
                    <span className={`status-pill status-${issue.status === "stalled" ? "stalled" : "running"}`}>{issue.status}</span>
                  </div>
                  <div>{issue.theme}</div>
                  <div className="activity-meta">
                    <span>{issue.milestone_stage.replace(/_/g, " ")}</span>
                    <span>escalation: {issue.escalation_stage.replace(/_/g, " ")}</span>
                    <span>severity: {issue.severity}</span>
                  </div>
                </div>
              </div>
            ))}
          </section>

          {votingRuns.length > 0 && (
            <section className="card">
              <div className="section-heading">
                <h2>Proxy voting runs</h2>
                <button className="link-button" onClick={() => onNavigate("voting")}>
                  Open Voting &rarr;
                </button>
              </div>
              <div className="table-wrap">
                <table className="data-table stack-on-phone">
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
                        <td data-label="Run">{r.run_id}</td>
                        <td data-label="Status"><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                        <td data-label="Companies">{r.completed_count}/{r.company_count}</td>
                        <td data-label="Awaiting decision">{r.review_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
