import { useEffect, useReducer, useState } from "react";
import { api } from "../api/client";
import { DocumentsStage } from "../components/DocumentsStage";
import { flowReducer, initialFlow, type StageOutput } from "../lib/stagedFlow";
import { UniversePicker } from "../components/UniversePicker";
import type { DiscoveryScheduleConfig, DocumentEvent, UniverseHandoff } from "../types";

interface Props {
  pendingUniverse?: UniverseHandoff | null;
  onSendUniverse?: (to: "extraction" | "transitionPlan", path: string, count: number) => void;
}

export function DocumentDiscovery({ pendingUniverse, onSendUniverse }: Props = {}) {
  const [flow, dispatch] = useReducer(flowReducer, initialFlow);
  const [replaced, setReplaced] = useState<StageOutput | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = replaced ?? (pendingUniverse ? { path: pendingUniverse.path, count: pendingUniverse.count } : null);
  const out = flow.documents.state === "done" ? flow.documents.output : null;

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
      <h1>Document Discovery</h1>
      <p className="help-text">Find each company’s investor-relations site and download new annual, sustainability and proxy reports and transcripts, on demand or on a schedule.</p>

      <section className="card">
        <h2>Run now (manual)</h2>
        {pendingUniverse && (
          <>
            <p className="status-text">
              Using {pendingUniverse.count} companies sent from {pendingUniverse.from}. Upload a different universe below
              to replace it.
            </p>
            <UniversePicker onResolved={(path, count) => setReplaced({ path, count })} />
          </>
        )}
        <DocumentsStage input={input} stage={flow.documents} dispatch={dispatch} view="run" />
        {error && <p className="error-text" role="alert">{error}</p>}
        {out && onSendUniverse && (
          <div className="toolbar">
            <span className="muted">Next, with the same {out.count} companies:</span>
            <button className="secondary" onClick={() => onSendUniverse("extraction", out.path, out.count)}>
              Extraction &rarr;
            </button>
            <button className="secondary" onClick={() => onSendUniverse("transitionPlan", out.path, out.count)}>
              Transition Plan &rarr;
            </button>
          </div>
        )}
      </section>

      {schedule && (
        <section className="card">
          <h2>Automatic schedule</h2>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={schedule.enabled}
              onChange={(e) => setSchedule({ ...schedule, enabled: e.target.checked })}
            />
            Enabled
          </label>
          <label className="field-label">
            Interval (hours)
            <input
              type="number"
              min={1}
              value={schedule.interval_hours}
              onChange={(e) => setSchedule({ ...schedule, interval_hours: Number(e.target.value) })}
            />
          </label>
          <label className="field-label">
            Universe path (server-side, from an upload above)
            <input
              value={schedule.universe_path ?? ""}
              onChange={(e) => setSchedule({ ...schedule, universe_path: e.target.value })}
              placeholder={input?.path ?? "runs/_universes/your_file.csv"}
            />
          </label>
          <button onClick={saveSchedule} disabled={busy}>
            Save schedule
          </button>
          {schedule.last_run_id && <p className="muted">Last scheduled run: {schedule.last_run_id}</p>}
        </section>
      )}

      <section className="card">
        <h2>New document feed</h2>
        <button onClick={refreshEvents}>Refresh</button>
        <div className="table-wrap">
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
              {events.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No new or updated documents yet. Scheduled scans add a row here for each document they find.
                  </td>
                </tr>
              )}
              {events.map((e) => (
                <tr key={e.event_id}>
                  <td>{new Date(e.created_at).toLocaleString()}</td>
                  <td>{e.event_type === "new_document" ? "New" : "Updated"}</td>
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
        </div>
      </section>
    </div>
  );
}
