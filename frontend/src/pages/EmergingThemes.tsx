import { Fragment, useEffect, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import type { CandidateStatus, EmergingThemeCandidate, EmergingThemesScheduleConfig, RunManifest } from "../types";

const STATUS_LABEL: Record<CandidateStatus, string> = {
  candidate: "candidate",
  under_review: "under review",
  promoted: "promoted",
  rejected: "rejected",
};

export function EmergingThemes() {
  const [universePath, setUniversePath] = useState<string | null>(null);
  const [companyCount, setCompanyCount] = useState(0);
  const [runId, setRunId] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<EmergingThemeCandidate[]>([]);
  const [pastRuns, setPastRuns] = useState<RunManifest[]>([]);
  const [schedule, setSchedule] = useState<EmergingThemesScheduleConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [taxonomyIdByTheme, setTaxonomyIdByTheme] = useState<Record<string, string>>({});

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refresh() {
    const s = await api.getEmergingThemesSchedule();
    setSchedule(s);
    const r = (await api.listRuns("emerging_themes")) as { runs: RunManifest[] };
    setPastRuns(r.runs);
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

  async function runNow() {
    if (!universePath) return;
    setBusy(true);
    setError(null);
    setCandidates([]);
    try {
      const res = await api.startEmergingThemesRun({ universe_path: universePath });
      setRunId(res.run_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function refreshCandidates() {
    if (!runId) return;
    const res = await api.getEmergingThemesCandidates(runId);
    setCandidates(res.candidates);
    refresh();
  }

  async function promote(themeId: string) {
    if (!runId) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.promoteEmergingTheme(runId, themeId, taxonomyIdByTheme[themeId]);
      setCandidates((prev) => prev.map((c) => (c.theme_id === themeId ? updated : c)));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reject(themeId: string) {
    if (!runId) return;
    setBusy(true);
    setError(null);
    try {
      await api.rejectEmergingTheme(runId, themeId);
      setCandidates((prev) => prev.map((c) => (c.theme_id === themeId ? { ...c, status: "rejected" } : c)));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h2>Emerging Themes Scanner</h2>
      <p className="help-text">
        Bottom-up candidate-theme discovery ("Tool 0"): scans public news, EDGAR full-text filings, and
        regulatory RSS flow for topics gaining momentum, clusters mentions that survive multiple reseeded
        stability reruns, and proposes a candidate theme once it has corroborating sources. Nothing here is
        auto-applied -- promoting a candidate only creates a new DRAFT taxonomy version, which still needs
        ratifying in the Taxonomy Library before any run can use it.
      </p>
      {error && <p className="error-text">{error}</p>}

      {schedule && (
        <section className="card">
          <h3>Automatic schedule</h3>
          <label className="checkbox-label">
            <input type="checkbox" checked={schedule.enabled} onChange={(e) => setSchedule({ ...schedule, enabled: e.target.checked })} />
            Enabled
          </label>
          <label className="field-label">Interval (hours)</label>
          <input type="number" min={1} value={schedule.interval_hours} onChange={(e) => setSchedule({ ...schedule, interval_hours: Number(e.target.value) })} />
          <label className="field-label">Universe path (server-side path from a prior upload below)</label>
          <input type="text" value={schedule.universe_path ?? ""} onChange={(e) => setSchedule({ ...schedule, universe_path: e.target.value })} />
          <button onClick={saveSchedule} disabled={busy}>
            Save schedule
          </button>
          {schedule.last_run_id && <p className="muted">Last scheduled run: {schedule.last_run_id}</p>}
        </section>
      )}

      <section className="card">
        <h3>Scan now</h3>
        <UniversePicker
          onResolved={(path, count) => {
            setUniversePath(path);
            setCompanyCount(count);
          }}
        />
        <button onClick={runNow} disabled={busy || !universePath}>
          Scan {companyCount || "..."} companies
        </button>
        {runId && (
          <>
            <RunProgress runId={runId} runType="emerging_themes" />
            <div className="toolbar">
              <button onClick={refreshCandidates}>Refresh candidates</button>
            </div>
          </>
        )}

        {candidates.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Theme</th>
                  <th>Status</th>
                  <th>Confidence</th>
                  <th>Velocity</th>
                  <th>First detected</th>
                  <th>Sources</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c) => (
                  <Fragment key={c.theme_id}>
                    <tr className="clickable-row" onClick={() => setExpanded(expanded === c.theme_id ? null : c.theme_id)}>
                      <td>{c.theme_name}</td>
                      <td><span className={`status-pill status-${c.status === "promoted" ? "completed" : c.status === "rejected" ? "failed" : "pending"}`}>{STATUS_LABEL[c.status]}</span></td>
                      <td>{c.confidence_score.toFixed(2)}</td>
                      <td>{c.signal_velocity}</td>
                      <td>{c.first_detected_date}</td>
                      <td>{c.corroborating_sources.length}</td>
                      <td>
                        {(c.status === "candidate" || c.status === "under_review") && (
                          <div className="inline-fields" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="text"
                              placeholder="extend taxonomy_id (optional)"
                              value={taxonomyIdByTheme[c.theme_id] ?? ""}
                              onChange={(e) => setTaxonomyIdByTheme((prev) => ({ ...prev, [c.theme_id]: e.target.value }))}
                            />
                            <button onClick={() => promote(c.theme_id)} disabled={busy}>Promote</button>
                            <button className="danger" onClick={() => reject(c.theme_id)} disabled={busy}>Reject</button>
                          </div>
                        )}
                        {c.status === "promoted" && <span className="muted">-&gt; {c.promoted_to_taxonomy_id} v{c.promoted_to_taxonomy_version}</span>}
                      </td>
                    </tr>
                    {expanded === c.theme_id && (
                      <tr>
                        <td colSpan={7} className="detail-cell">
                          <p>{c.description}</p>
                          <p><strong>Rationale:</strong> {c.rationale}</p>
                          <p><strong>Economic rationale:</strong> {c.economic_rationale}</p>
                          {c.candidate_sectors_companies.length > 0 && (
                            <div className="chip-row">
                              {c.candidate_sectors_companies.map((id) => (
                                <span className="chip" key={id}>{id}</span>
                              ))}
                            </div>
                          )}
                          <ul className="citation-list">
                            {c.corroborating_sources.map((s) => (
                              <li key={s.mention_id}>
                                [{s.source_type}] <a href={s.url} target="_blank" rel="noreferrer">{s.url}</a> -- "{s.quote}"{!s.grounded && <span className="muted"> (ungrounded)</span>}
                              </li>
                            ))}
                          </ul>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h3>Past runs</h3>
        {pastRuns.length === 0 && <p className="muted">No emerging-themes runs yet.</p>}
        {pastRuns.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Status</th>
                  <th>Scanned</th>
                  <th>Candidates</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {pastRuns.map((r) => (
                  <tr key={r.run_id}>
                    <td>{r.run_id}</td>
                    <td><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                    <td>{r.completed_count}/{r.company_count}</td>
                    <td>{r.review_count}</td>
                    <td>{new Date(r.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
