import { useEffect, useState } from "react";
import { api } from "../api/client";
import { UniversePicker } from "./UniversePicker";
import { reportText, statusText } from "../lib/xbrlTags";
import type { RunManifest, XbrlCompanyStatus } from "../types";

type ResultRow = XbrlCompanyStatus & { _key: string };
type ErrorRow = { key: string; error: string };

const POLL_MS = 2500;
const POLL_CAP_MS = 20 * 60 * 1000; // stop polling a run that never finishes; "Check again" resumes
// ponytail: the status table reads the first 500 results (the API's page cap); page it if runs grow past that.
const RESULT_LIMIT = 500;
const RUN_LABEL: Record<string, string> = {
  pending: "Starting",
  running: "Running",
  completed: "Finished",
  partially_completed: "Finished with failures",
  failed: "Failed",
  cancelled: "Cancelled",
};
const msg = (err: unknown) => (err as Error).message;

const inProgress = (m: RunManifest | null) => m?.status === "pending" || m?.status === "running";

/** XBRL Facts, Fetch area: start a fetch over a universe, poll its status, retry failures. */
export function XbrlFetchArea({ tags }: { tags: string[] }) {
  const [universe, setUniverse] = useState<{ path: string; count: number } | null>(null);
  const [mode, setMode] = useState<"all" | "selected">("all");
  const [refresh, setRefresh] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [manifest, setManifest] = useState<RunManifest | null>(null);
  const [results, setResults] = useState<{ total: number; results: ResultRow[] }>({ total: 0, results: [] });
  const [errors, setErrors] = useState<ErrorRow[]>([]);
  const [pollKey, setPollKey] = useState(0); // bumped to (re)start polling: new run, retry, "Check again"
  const [stalled, setStalled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let stopped = false;
    let timer: number | undefined;
    const until = Date.now() + POLL_CAP_MS;
    setStalled(false);
    const schedule = (ms: number) => (Date.now() < until ? (timer = window.setTimeout(tick, ms)) : setStalled(true));
    const tick = async () => {
      try {
        const [m, r, e] = await Promise.all([
          api.getXbrlRun(runId) as Promise<RunManifest>,
          api.getXbrlResults(runId, 0, RESULT_LIMIT) as Promise<{ total: number; results: ResultRow[] }>,
          api.getRunErrors(runId),
        ]);
        if (stopped) return;
        setManifest(m);
        setResults(r);
        setErrors(e.errors);
        setPollError(null);
        if (!inProgress(m)) return;
        schedule(POLL_MS);
      } catch (err) {
        if (stopped) return;
        setPollError(msg(err)); // keep trying, slower, in case the backend comes back
        schedule(POLL_MS * 4);
      }
    };
    tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [runId, pollKey]);

  const succeeded = new Set(results.results.map((r) => r._key));
  const latestError = new Map(errors.map((e) => [e.key, e.error])); // later rows win
  const failed = [...latestError].filter(([key]) => !succeeded.has(key)).map(([key, error]) => ({ key, error }));
  const running = inProgress(manifest) && !stalled;
  const canRetry = manifest !== null && !inProgress(manifest) && manifest.failed_count > 0;
  const noTags = mode === "selected" && tags.length === 0;

  async function start() {
    if (!universe) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.startXbrlRun({ universe_path: universe.path, tags: mode === "selected" ? tags : undefined, refresh });
      setManifest(null);
      setResults({ total: 0, results: [] });
      setErrors([]);
      setRunId(res.run_id); // a new run id (re)starts polling
    } catch (err) {
      setError(`Could not start the fetch (${msg(err)}).`);
    } finally {
      setBusy(false);
    }
  }

  async function retryFailed() {
    if (!runId || !manifest) return;
    setBusy(true);
    setError(null);
    try {
      await api.retryXbrlRun(runId);
      // The server marks the run running before it answers; show that until the next poll confirms it.
      setManifest({ ...manifest, status: "running" });
      setPollKey((k) => k + 1);
    } catch (err) {
      setError(`Could not retry (${msg(err)}).`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="xbrl-fetch-title">
      <h2 id="xbrl-fetch-title">Fetch</h2>
      <UniversePicker onResolved={(path, count) => setUniverse({ path, count })} />
      <fieldset className="xbrl-choice">
        <legend className="field-label">Tags to fetch</legend>
        <label className="checkbox-label">
          <input type="radio" name="xbrl-tag-mode" checked={mode === "all"} onChange={() => setMode("all")} />
          All tags
        </label>
        <label className="checkbox-label">
          <input type="radio" name="xbrl-tag-mode" checked={mode === "selected"} onChange={() => setMode("selected")} />
          Selected tags ({tags.length} chosen in Tags below)
        </label>
      </fieldset>
      <label className="checkbox-label">
        <input type="checkbox" checked={refresh} onChange={(e) => setRefresh(e.target.checked)} />
        Refresh: download again even if a recent copy is cached
      </label>
      {noTags && <p className="help-text">Choose at least one tag in the Tags section, or fetch all tags.</p>}
      {!universe && <p className="help-text">Upload or pick a company universe to start.</p>}
      <button onClick={start} disabled={busy || !universe || noTags || (running && !pollError)}>
        Start fetch{universe ? ` for ${universe.count.toLocaleString()} companies` : ""}
      </button>
      <div aria-live="polite">{error && <p className="error-text">{error}</p>}</div>

      {runId && (
        <div className="xbrl-run">
          <p className="toolbar" aria-live="polite">
            <span className={`status-pill status-${manifest?.status ?? "pending"}`}>
              {RUN_LABEL[manifest?.status ?? "pending"] ?? manifest?.status}
            </span>
            {manifest && (
              <span className="muted">
                {manifest.completed_count.toLocaleString()} of {manifest.company_count.toLocaleString()} companies fetched,{" "}
                {manifest.failed_count.toLocaleString()} failed
              </span>
            )}
            <span className="muted mono">{runId}</span>
          </p>
          {pollError && <p className="error-text">Run status could not be loaded ({pollError}). Trying again.</p>}
          {stalled && (
            <p className="error-text">
              Still running after {POLL_CAP_MS / 60000} minutes, so this page stopped checking; the run may still be going.{" "}
              <button className="link-button" onClick={() => setPollKey((k) => k + 1)}>
                Check again
              </button>
            </p>
          )}
          {manifest?.error && <p className="error-text">The run stopped: {manifest.error}</p>}
          <div className="table-wrap">
            <table className="data-table stack-on-phone">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Status</th>
                  <th>Annual report</th>
                  <th>Facts</th>
                </tr>
              </thead>
              <tbody>
                {results.results.length + failed.length === 0 && (
                  <tr>
                    <td colSpan={4} className="muted">
                      {inProgress(manifest) ? "Waiting for the first company…" : "No companies were processed."}
                    </td>
                  </tr>
                )}
                {results.results.map((r) => (
                  <tr key={r._key}>
                    <td data-label="Company">{r.company_id}</td>
                    <td data-label="Status">{statusText(r.status)}</td>
                    <td data-label="Annual report">{reportText(r.report)}</td>
                    <td data-label="Facts" className="mono">{r.fact_count.toLocaleString()}</td>
                  </tr>
                ))}
                {failed.map((f) => (
                  <tr key={f.key}>
                    <td data-label="Company">{f.key}</td>
                    <td data-label="Status" className="error-text">{statusText("error")}</td>
                    <td data-label="Annual report">Not attempted</td>
                    <td data-label="Facts" className="mono">0</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {results.total > results.results.length && (
            <p className="muted">Showing the first {results.results.length.toLocaleString()} of {results.total.toLocaleString()} fetched companies.</p>
          )}
          {failed.length > 0 && (
            <>
              <h3>Errors</h3>
              <ul className="xbrl-errors">
                {failed.map((f) => (
                  <li key={f.key}>
                    <span className="mono">{f.key}</span>: {f.error}
                  </li>
                ))}
              </ul>
            </>
          )}
          {canRetry && (
            <button className="secondary" onClick={retryFailed} disabled={busy}>
              Retry failed
            </button>
          )}
        </div>
      )}
    </section>
  );
}
