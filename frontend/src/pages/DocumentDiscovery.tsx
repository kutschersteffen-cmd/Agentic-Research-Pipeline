import { useEffect, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import type { DiscoveryCompanyResult, DiscoveryScheduleConfig, DocumentEvent } from "../types";

export function DocumentDiscovery() {
  const [universePath, setUniversePath] = useState<string | null>(null);
  const [companyCount, setCompanyCount] = useState(0);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<DiscoveryCompanyResult[]>([]);

  const [schedule, setSchedule] = useState<DiscoveryScheduleConfig | null>(null);
  const [events, setEvents] = useState<DocumentEvent[]>([]);

  useEffect(() => {
    api.getDiscoverySchedule().then((s) => setSchedule(s as DiscoveryScheduleConfig));
    refreshEvents();
    const timer = window.setInterval(refreshEvents, 10000);
    return () => window.clearInterval(timer);
  }, []);

  async function refreshEvents() {
    const res = (await api.getDiscoveryEvents()) as { events: DocumentEvent[] };
    setEvents(res.events.slice().reverse());
  }

  async function refreshResults() {
    if (!runId) return;
    const res = (await api.getDiscoveryResults(runId)) as { results: DiscoveryCompanyResult[] };
    setResults(res.results);
  }

  async function runNow() {
    if (!universePath) return;
    setBusy(true);
    setError(null);
    setResults([]);
    try {
      const res = await api.startDiscoveryRun({ universe_path: universePath });
      setRunId(res.run_id);
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
      const saved = (await api.updateDiscoverySchedule(schedule)) as DiscoveryScheduleConfig;
      setSchedule(saved);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h2>Document Discovery</h2>
      <p className="help-text">
        Finds each company's investor-relations site, crawls it (bounded, robots.txt-respecting, same-domain only)
        for annual reports / sustainability reports / proxy statements / transcripts, downloads new or changed
        documents into the local store, and raises an event the moment something new appears -- run manually or on
        an automatic schedule.
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
          Search for documents across {companyCount || "..."} companies
        </button>
        {error && <p className="error-text">{error}</p>}
        {runId && <RunProgress runId={runId} runType="extraction" />}
        {runId && (
          <>
            <button onClick={refreshResults}>Refresh results</button>
            {results.length > 0 && (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Company</th>
                    <th>Homepage used</th>
                    <th>Status</th>
                    <th>Documents found</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <tr key={r.company_id}>
                      <td>{r.name}</td>
                      <td>{r.homepage_used ?? "(none known)"}</td>
                      <td>
                        {r.homepage_unreachable ? (
                          <span className="error-text" title={r.crawl_error ?? undefined}>
                            ⚠️ site unreachable{r.crawl_error ? `: ${r.crawl_error}` : ""}
                          </span>
                        ) : !r.homepage_used ? (
                          <span className="muted">no homepage known</span>
                        ) : (
                          "ok"
                        )}
                      </td>
                      <td>{r.documents_found.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
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
          {schedule.last_run_id && <p className="muted">Last scheduled run: {schedule.last_run_id}</p>}
        </section>
      )}

      <section className="card">
        <h3>New document feed</h3>
        <button onClick={refreshEvents}>Refresh</button>
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Company</th>
              <th>Doc type</th>
              <th>URL</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.event_id}>
                <td>{new Date(e.created_at).toLocaleString()}</td>
                <td>{e.event_type === "new_document" ? "🆕 new" : "♻️ updated"}</td>
                <td>{e.company_name ?? e.company_id}</td>
                <td>{e.document.doc_type}</td>
                <td>
                  <a href={e.document.url} target="_blank" rel="noreferrer">
                    {e.document.url}
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
