import { Fragment, useEffect, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import type { EmergingThemeCandidate, EmergingThemesScheduleConfig } from "../types";

interface Props {
  onPromoted?: (taxonomyId: string) => void;
}

/** Standing scan of public news/filings/regulatory flow for early-stage
 * themes -- the Detect/Output layers ahead of the Taxonomy Library. Every
 * candidate needs an explicit promote (or reject) here before it becomes a
 * taxonomy; nothing crosses that gate automatically. */
export function EmergingThemes({ onPromoted }: Props = {}) {
  const [universePath, setUniversePath] = useState<string | null>(null);
  const [companyCount, setCompanyCount] = useState(0);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [schedule, setSchedule] = useState<EmergingThemesScheduleConfig | null>(null);

  const [loadRunId, setLoadRunId] = useState("");
  const [candidates, setCandidates] = useState<EmergingThemeCandidate[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [taxonomyIdByTheme, setTaxonomyIdByTheme] = useState<Record<string, string>>({});
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  useEffect(() => {
    api.getEmergingThemesSchedule().then((s) => setSchedule(s as EmergingThemesScheduleConfig));
  }, []);

  async function runNow() {
    if (!universePath) return;
    setBusy(true);
    setError(null);
    setCandidates([]);
    try {
      const res = await api.startEmergingThemesRun({ universe_path: universePath });
      setRunId(res.run_id);
      setLoadRunId(res.run_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveSchedule() {
    if (!schedule) return;
    setBusy(true);
    try {
      const saved = (await api.updateEmergingThemesSchedule(schedule)) as EmergingThemesScheduleConfig;
      setSchedule(saved);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function loadCandidates() {
    if (!loadRunId) return;
    setError(null);
    try {
      const res = await api.listEmergingThemeCandidates(loadRunId);
      setCandidates(res.candidates);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function promote(c: EmergingThemeCandidate) {
    setRowBusy(c.theme_id);
    setError(null);
    try {
      const updated = await api.promoteEmergingThemeCandidate(loadRunId, c.theme_id, taxonomyIdByTheme[c.theme_id]);
      setCandidates((prev) => prev.map((x) => (x.theme_id === c.theme_id ? updated : x)));
      if (updated.promoted_to_taxonomy_id) onPromoted?.(updated.promoted_to_taxonomy_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRowBusy(null);
    }
  }

  async function reject(c: EmergingThemeCandidate) {
    setRowBusy(c.theme_id);
    setError(null);
    try {
      await api.rejectEmergingThemeCandidate(loadRunId, c.theme_id);
      setCandidates((prev) => prev.map((x) => (x.theme_id === c.theme_id ? { ...x, status: "rejected" } : x)));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRowBusy(null);
    }
  }

  return (
    <div className="page">
      <h2>Emerging Themes</h2>
      <p className="help-text">
        Scans public news (GDELT), SEC EDGAR full-text search, and regulatory RSS feeds across a company universe,
        clusters the signal, and surfaces topics with no prior-period lineage ("births") as candidate themes --
        source-linked, with a required economic rationale. Nothing reaches the Taxonomy Library without an explicit
        promote decision below.
      </p>

      <section className="card">
        <h3>Run now (manual)</h3>
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
          {schedule.last_run_id && (
            <p className="muted">
              Last scheduled run: {schedule.last_run_id}{" "}
              <button className="link-button" onClick={() => setLoadRunId(schedule.last_run_id!)}>
                use it below &rarr;
              </button>
            </p>
          )}
        </section>
      )}

      <section className="card">
        <div className="section-heading">
          <h3>Candidates</h3>
        </div>
        <label className="field-label">Run ID</label>
        <div className="toolbar">
          <input value={loadRunId} onChange={(e) => setLoadRunId(e.target.value)} placeholder="emergthemerun_..." />
          <button onClick={loadCandidates} disabled={!loadRunId}>
            Load candidates
          </button>
        </div>
        {candidates.length === 0 && <p className="muted">No candidates loaded yet.</p>}
        {candidates.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Theme</th>
                <th>First detected</th>
                <th>Velocity</th>
                <th>Confidence</th>
                <th>Sources</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => (
                <Fragment key={c.theme_id}>
                  <tr>
                    <td>
                      <button className="link-button" onClick={() => setExpanded(expanded === c.theme_id ? null : c.theme_id)}>
                        {c.theme_name}
                      </button>
                    </td>
                    <td>{c.first_detected_date}</td>
                    <td>{c.signal_velocity}</td>
                    <td>{c.confidence_score.toFixed(2)}</td>
                    <td>{c.corroborating_sources.length}</td>
                    <td><span className={`status-pill status-${c.status === "candidate" ? "pending" : c.status === "promoted" ? "completed" : c.status === "rejected" ? "failed" : "running"}`}>{c.status}</span></td>
                    <td>
                      {c.status === "candidate" || c.status === "under_review" ? (
                        <div className="toolbar">
                          <input
                            placeholder="existing taxonomy id (optional)"
                            value={taxonomyIdByTheme[c.theme_id] ?? ""}
                            onChange={(e) => setTaxonomyIdByTheme({ ...taxonomyIdByTheme, [c.theme_id]: e.target.value })}
                          />
                          <button onClick={() => promote(c)} disabled={rowBusy === c.theme_id}>
                            Promote
                          </button>
                          <button onClick={() => reject(c)} disabled={rowBusy === c.theme_id}>
                            Reject
                          </button>
                        </div>
                      ) : c.status === "promoted" ? (
                        <span className="muted">&rarr; taxonomy {c.promoted_to_taxonomy_id}</span>
                      ) : (
                        <span className="muted">--</span>
                      )}
                    </td>
                  </tr>
                  {expanded === c.theme_id && (
                    <tr>
                      <td colSpan={7}>
                        <p>{c.description}</p>
                        <p><strong>Rationale:</strong> {c.rationale}</p>
                        <p><strong>Economic rationale:</strong> {c.economic_rationale}</p>
                        {c.candidate_sectors_companies.length > 0 && (
                          <p><strong>Companies:</strong> {c.candidate_sectors_companies.join(", ")}</p>
                        )}
                        {c.corroborating_sources.length > 0 && (
                          <ul>
                            {c.corroborating_sources.map((s) => (
                              <li key={s.mention_id}>
                                <a href={s.url} target="_blank" rel="noreferrer">{s.source_type}</a>
                                {s.grounded ? "" : " (ungrounded)"}: "{s.quote}"
                              </li>
                            ))}
                          </ul>
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
    </div>
  );
}
