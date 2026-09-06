import { Fragment, useEffect, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { CandidateStatusBadge, ConfidenceBadge } from "../components/ConfidenceBadge";
import { MentionCitationList } from "../components/MentionCitationList";
import type { EmergingThemeCandidate, EmergingThemesScheduleConfig, RunManifest } from "../types";

interface Props {
  onNavigate?: (tab: "taxonomy") => void;
}

export function EmergingThemesDetector({ onNavigate }: Props = {}) {
  const [universePath, setUniversePath] = useState<string | null>(null);
  const [companyCount, setCompanyCount] = useState(0);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [recentRuns, setRecentRuns] = useState<RunManifest[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<EmergingThemeCandidate[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [taxonomyIdInputs, setTaxonomyIdInputs] = useState<Record<string, string>>({});
  const [reasonInputs, setReasonInputs] = useState<Record<string, string>>({});

  const [schedule, setSchedule] = useState<EmergingThemesScheduleConfig | null>(null);

  useEffect(() => {
    refreshRecentRuns();
    api.getEmergingThemesSchedule().then((s) => setSchedule(s));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshRecentRuns() {
    const res = (await api.listRuns("emerging_themes")) as { runs: RunManifest[] };
    setRecentRuns(res.runs);
  }

  async function refreshCandidates(id: string) {
    const res = await api.getEmergingThemesCandidates(id);
    setCandidates(res.candidates);
  }

  async function runNow() {
    if (!universePath) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.startEmergingThemesRun({ universe_path: universePath });
      setRunId(res.run_id);
      setSelectedRunId(res.run_id);
      setCandidates([]);
      refreshRecentRuns();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function selectRun(id: string) {
    setSelectedRunId(id);
    setExpanded(null);
    refreshCandidates(id);
  }

  async function promote(candidate: EmergingThemeCandidate) {
    if (!selectedRunId) return;
    const reason = (reasonInputs[candidate.theme_id] ?? "").trim();
    if (!reason) return;
    setBusy(true);
    setError(null);
    try {
      await api.promoteEmergingThemeCandidate(selectedRunId, candidate.theme_id, reason, taxonomyIdInputs[candidate.theme_id] || null);
      await refreshCandidates(selectedRunId);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reject(candidate: EmergingThemeCandidate) {
    if (!selectedRunId) return;
    const reason = (reasonInputs[candidate.theme_id] ?? "").trim();
    if (!reason) return;
    setBusy(true);
    setError(null);
    try {
      await api.rejectEmergingThemeCandidate(selectedRunId, candidate.theme_id, reason);
      await refreshCandidates(selectedRunId);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function disconfirm(candidate: EmergingThemeCandidate) {
    if (!selectedRunId) return;
    const reason = (reasonInputs[candidate.theme_id] ?? "").trim();
    if (!reason) return;
    setBusy(true);
    setError(null);
    try {
      await api.disconfirmEmergingThemeCandidate(selectedRunId, candidate.theme_id, reason);
      await refreshCandidates(selectedRunId);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveSchedule() {
    if (!schedule) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api.updateEmergingThemesSchedule(schedule);
      setSchedule(saved);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h2>Emerging Themes Detector</h2>
      <p className="help-text">
        "Tool 0" of the research stack: watches public news, filings, and regulatory flow across a universe for
        topics nobody has named yet -- clusters mentions with period-over-period lineage tracking, and proposes a
        candidate theme only when it's genuinely new (no lineage back to a prior period), backed by at least two
        independent sources. No candidate reaches the Taxonomy Library without an explicit promote below.
      </p>

      <section className="card">
        <h3>Run a scan now</h3>
        <UniversePicker
          onResolved={(path, count) => {
            setUniversePath(path);
            setCompanyCount(count);
          }}
        />
        <button onClick={runNow} disabled={busy || !universePath}>
          Scan for emerging themes across {companyCount || "..."} companies
        </button>
        {error && <p className="error-text">{error}</p>}
        {runId && <RunProgress runId={runId} runType="emerging_themes" />}
      </section>

      <section className="card">
        <h3>Recent scans</h3>
        <button onClick={refreshRecentRuns}>Refresh</button>
        {recentRuns.length === 0 ? (
          <p className="muted">No scans yet -- run one above, or enable the automatic schedule below.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Status</th>
                <th>Awaiting review</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {recentRuns.map((r) => (
                <tr key={r.run_id} className="clickable-row" onClick={() => selectRun(r.run_id)}>
                  <td>{r.run_id}</td>
                  <td><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                  <td>{r.review_count}</td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td>
                    <button onClick={(e) => { e.stopPropagation(); selectRun(r.run_id); }}>View candidates</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {selectedRunId && (
        <section className="card">
          <h3>Candidates -- {selectedRunId}</h3>
          <button onClick={() => refreshCandidates(selectedRunId)}>Refresh candidates</button>
          {candidates.length === 0 ? (
            <p className="muted">No candidates for this run (nothing survived the independent-source-minimum and lineage-birth filters).</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Theme</th>
                  <th>Confidence</th>
                  <th>Status</th>
                  <th>Companies</th>
                  <th>Velocity</th>
                  <th>First detected</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c) => (
                  <Fragment key={c.theme_id}>
                    <tr onClick={() => setExpanded(expanded === c.theme_id ? null : c.theme_id)} className="clickable-row">
                      <td>{c.theme_name}</td>
                      <td><ConfidenceBadge value={c.confidence_score} /></td>
                      <td><CandidateStatusBadge status={c.status} /></td>
                      <td>
                        <div className="chip-row">
                          {c.candidate_sectors_companies.map((id) => (
                            <span className="chip" key={id}>{id}</span>
                          ))}
                        </div>
                      </td>
                      <td title="This period's mention count vs. baseline -- see the expanded row for what this cluster's baseline was.">{c.signal_velocity.toFixed(2)}&times;</td>
                      <td>{c.first_detected_date}</td>
                    </tr>
                    {expanded === c.theme_id && (
                      <tr>
                        <td colSpan={6} className="detail-cell">
                          <p>{c.description}</p>
                          <p>
                            <strong>Discovery signal:</strong> novelty {Math.round(c.novelty * 100)}%, breadth{" "}
                            {Math.round(c.breadth * 100)}% of the scanned universe, velocity {c.signal_velocity.toFixed(2)}&times; baseline,{" "}
                            {c.persistence > 0 ? `persisted ${c.persistence} period(s)` : "first period seen"}, action evidence{" "}
                            {Math.round(c.action_score * 100)}% (share of evidence describing a concrete action, not just a mention),{" "}
                            materiality {Math.round(c.materiality * 100)}% (share linked to revenue/margin/cash flow/assets/risk),{" "}
                            contradiction {Math.round(c.contradiction * 100)}% (share describing a delay, cancellation, impairment, or target withdrawal).
                          </p>
                          <p><strong>Rationale:</strong> {c.rationale}</p>
                          <p><strong>Why this would move markets:</strong> {c.economic_rationale}</p>
                          <p><strong>Corroborating sources:</strong></p>
                          <MentionCitationList citations={c.corroborating_sources} />

                          {c.xbrl_corroboration.length > 0 && (
                            <>
                              <p><strong>SEC XBRL corroboration:</strong></p>
                              <ul>
                                {c.xbrl_corroboration.map((x) => (
                                  <li key={x.company_id}>
                                    {x.company_id}: CapEx{" "}
                                    {x.capex_pct_change != null ? `${x.capex_pct_change >= 0 ? "+" : ""}${Math.round(x.capex_pct_change * 100)}%` : "n/a"},{" "}
                                    R&amp;D {x.rnd_pct_change != null ? `${x.rnd_pct_change >= 0 ? "+" : ""}${Math.round(x.rnd_pct_change * 100)}%` : "n/a"}{" "}
                                    <span className="muted">(YoY, most recent annual filing)</span>
                                  </li>
                                ))}
                              </ul>
                            </>
                          )}

                          {c.contradiction_evidence.length > 0 && (
                            <>
                              <p><strong>Contradicting evidence</strong> <span className="muted">(retained regardless of status -- delays, cancellations, impairments, or target withdrawals):</span></p>
                              <MentionCitationList citations={c.contradiction_evidence} />
                            </>
                          )}

                          {(c.status === "candidate" || c.status === "under_review") && (
                            <div className="toolbar">
                              <input
                                placeholder="Reason (required)"
                                value={reasonInputs[c.theme_id] ?? ""}
                                onChange={(e) => setReasonInputs({ ...reasonInputs, [c.theme_id]: e.target.value })}
                              />
                              <input
                                placeholder="Existing ratified taxonomy_id (optional)"
                                value={taxonomyIdInputs[c.theme_id] ?? ""}
                                onChange={(e) => setTaxonomyIdInputs({ ...taxonomyIdInputs, [c.theme_id]: e.target.value })}
                              />
                              <button onClick={() => promote(c)} disabled={busy || !(reasonInputs[c.theme_id] ?? "").trim()}>
                                Promote
                              </button>
                              <button onClick={() => reject(c)} disabled={busy || !(reasonInputs[c.theme_id] ?? "").trim()} className="danger">
                                Reject
                              </button>
                              <button onClick={() => disconfirm(c)} disabled={busy || !(reasonInputs[c.theme_id] ?? "").trim()} className="danger">
                                Disconfirm
                              </button>
                            </div>
                          )}
                          {c.status === "promoted" && (
                            <p className="status-text">
                              Promoted &rarr; taxonomy {c.promoted_to_taxonomy_id} v{c.promoted_to_taxonomy_version}
                              {c.decision_reason && <> -- "{c.decision_reason}"</>}.{" "}
                              {onNavigate && (
                                <button className="link-button" onClick={() => onNavigate("taxonomy")}>
                                  View in Taxonomy Library
                                </button>
                              )}
                            </p>
                          )}
                          {c.status === "rejected" && c.decision_reason && (
                            <p className="muted">Rejected -- "{c.decision_reason}"</p>
                          )}
                          {c.status === "disconfirmed" && c.decision_reason && (
                            <p className="muted">Disconfirmed -- "{c.decision_reason}"</p>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {schedule && (
        <section className="card">
          <h3>Automatic schedule</h3>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={schedule.enabled}
              onChange={(e) => setSchedule({ ...schedule, enabled: e.target.checked })}
            />
            Enabled
          </label>
          <label className="field-label">Interval (hours)</label>
          <input
            type="number"
            min={1}
            value={schedule.interval_hours}
            onChange={(e) => setSchedule({ ...schedule, interval_hours: Number(e.target.value) })}
          />
          <label className="field-label">Universe path (server-side, from an upload above)</label>
          <input
            value={schedule.universe_path ?? ""}
            onChange={(e) => setSchedule({ ...schedule, universe_path: e.target.value })}
            placeholder={universePath ?? "runs/_universes/your_file.csv"}
          />
          <button onClick={saveSchedule} disabled={busy}>
            Save schedule
          </button>
          {schedule.last_run_id && <p className="muted">Last scheduled run: {schedule.last_run_id}</p>}
        </section>
      )}
    </div>
  );
}
