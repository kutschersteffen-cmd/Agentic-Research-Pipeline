import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { UniversePicker } from "./UniversePicker";
import { when } from "../lib/runs";
import { canRetryFetch, keyLabel, reportText, statusText } from "../lib/xbrlTags";
import type { RunManifest, UniverseHandoff, WorkbenchResponse, XbrlCompanyStatus, XbrlRunMarket } from "../types";
import { pollAfter } from "../lib/poll";

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
export function XbrlFetchArea({
  tags,
  onSettled,
  selectedRunId: runId,
  onSelectRun,
  pendingUniverse,
}: {
  tags: string[];
  onSettled?: () => void;
  selectedRunId: string | null; // from the URL (#/xbrl/<run id>): refresh, Back and a pasted link reattach
  onSelectRun: (runId: string) => void;
  pendingUniverse?: UniverseHandoff | null;
}) {
  const [picked, setPicked] = useState<{ path: string; count: number } | null>(null);
  const universe = picked ?? (pendingUniverse ? { path: pendingUniverse.path, count: pendingUniverse.count } : null); // a pick replaces the hand-over
  const [market, setMarket] = useState<XbrlRunMarket>("auto");
  const [routes, setRoutes] = useState<WorkbenchResponse["counts"]["routes"] | null>(null);
  const [routesError, setRoutesError] = useState<string | null>(null);
  const [routesLoading, setRoutesLoading] = useState(false);
  const routeReq = useRef(0); // only the latest preview request may write state
  const [mode, setMode] = useState<"all" | "selected">("all");
  const [refresh, setRefresh] = useState(false);
  const [runs, setRuns] = useState<RunManifest[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [manifest, setManifest] = useState<RunManifest | null>(null);
  const [results, setResults] = useState<{ total: number; results: ResultRow[] }>({ total: 0, results: [] });
  const [errors, setErrors] = useState<ErrorRow[]>([]);
  const [pollKey, setPollKey] = useState(0); // bumped to (re)start polling: new run, retry, "Check again"
  const [stalled, setStalled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    (api.listRuns("xbrl_fetch") as Promise<{ runs: RunManifest[] }>)
      .then((res) => live && (setRuns([...res.runs].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))), setRunsError(null)))
      .catch((err) => live && setRunsError(msg(err)));
    return () => {
      live = false;
    };
  }, [runId, manifest?.status, manifest?.completed_count]); // a new run, or progress, changes the labels

  const universePath = universe?.path;
  useEffect(() => {
    const req = ++routeReq.current;
    setRoutes(null);
    setRoutesError(null);
    setRoutesLoading(false);
    if (market !== "auto" || !universePath) return;
    setRoutesLoading(true);
    api
      .universeWorkbench({ universe_path: universePath, availability: false })
      .then((res) => req === routeReq.current && (setRoutes(res.counts.routes), setRoutesLoading(false)))
      .catch((err) => req === routeReq.current && (setRoutesError(msg(err)), setRoutesLoading(false)));
  }, [market, universePath]);

  useEffect(() => {
    // Another run was chosen (or none): drop the last one's table before its own arrives.
    setManifest(null);
    setResults({ total: 0, results: [] });
    setErrors([]);
    setPollError(null);
    setError(null);
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    let stopped = false;
    let cancel = () => {};
    const until = Date.now() + POLL_CAP_MS;
    setStalled(false);
    const schedule = (ms: number) => (Date.now() < until ? (cancel = pollAfter(tick, ms)) : setStalled(true));
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
        if (!inProgress(m)) {
          onSettled?.(); // stored files changed: the Files list reloads
          return;
        }
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
      cancel();
    };
  }, [runId, pollKey, onSettled]); // onSettled must be stable (useCallback) or polling restarts

  const succeeded = new Set(results.results.map((r) => r._key));
  const latestError = new Map(errors.map((e) => [e.key, e.error])); // later rows win
  // an auto run mixes SEC (CIK) and ESEF (LEI) rows: the shared column gets a neutral header
  const keyHead =
    manifest?.params?.market === "auto" ? "CIK / LEI" : keyLabel(results.results[0]?.market ?? (market === "esef" ? "esef" : "sec"));
  const failed = [...latestError].filter(([key]) => !succeeded.has(key)).map(([key, error]) => ({ key, error }));
  // A started run counts as running until its first manifest arrives, so Start cannot fire twice.
  const running = runId !== null && (manifest === null || inProgress(manifest)) && !stalled;
  const canRetry = canRetryFetch(manifest, stalled);
  const noTags = mode === "selected" && tags.length === 0;

  async function start() {
    if (!universe) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.startXbrlRun({ universe_path: universe.path, tags: mode === "selected" ? tags : undefined, refresh, market });
      onSelectRun(res.run_id); // the URL carries the run id; a new id (re)starts polling
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
      const text = msg(err);
      setError(`Could not retry (${text}).${/^409/.test(text) ? " This page keeps checking the run." : ""}`);
      if (/^409/.test(text)) {
        setStalled(false); // the run is executing after all: resume polling
        setPollKey((k) => k + 1);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="xbrl-fetch-title">
      <h2 id="xbrl-fetch-title">Fetch</h2>
      <fieldset className="xbrl-choice">
        <legend className="field-label">Market</legend>
        <label className="checkbox-label">
          <input type="radio" name="xbrl-market" checked={market === "auto"} onChange={() => setMarket("auto")} />
          Auto
        </label>
        <label className="checkbox-label">
          <input type="radio" name="xbrl-market" checked={market === "sec"} onChange={() => setMarket("sec")} />
          US (SEC)
        </label>
        <label className="checkbox-label">
          <input type="radio" name="xbrl-market" checked={market === "esef"} onChange={() => setMarket("esef")} />
          EU (ESEF)
        </label>
      </fieldset>
      {market === "esef" && <p className="help-text">The universe file needs an lei column.</p>}
      <UniversePicker onResolved={(path, count) => setPicked({ path, count })} />
      {pendingUniverse && universe?.path === pendingUniverse.path && (
        <p className="status-text">
          Using {pendingUniverse.count} companies sent from {pendingUniverse.from}. Pick a different universe below to replace it.
        </p>
      )}
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
      {market === "auto" && universe && (
        <p className="help-text" aria-live="polite">
          {routesLoading && "Checking where each company's XBRL comes from…"}
          {routesError && <span className="error-text">Routing preview failed ({routesError}).</span>}
          {routes && `SEC ${routes.sec} · ESEF ${routes.esef} · no source ${routes.no_source} · not routed ${routes.unrouted}`}
        </p>
      )}
      {noTags && <p className="help-text">Choose at least one tag in the Tags section, or fetch all tags.</p>}
      {!universe && <p className="help-text">Upload or pick a company universe to start.</p>}
      <button onClick={start} disabled={busy || !universe || noTags || (running && !pollError)}>
        Start fetch{universe ? ` for ${universe.count.toLocaleString()} companies` : ""}
      </button>
      <div aria-live="polite">{error && <p className="error-text">{error}</p>}</div>

      <label className="field-label">
        Fetch run
        <select value={runId ?? ""} onChange={(e) => e.target.value && onSelectRun(e.target.value)} disabled={!runs && !runsError}>
          <option value="" disabled>
            {!runs && !runsError ? "Loading…" : runs?.length === 0 ? "No fetch run yet" : "Select a run to see its status…"}
          </option>
          {runId && !runs?.some((r) => r.run_id === runId) && <option value={runId}>{runId}</option>}
          {runs?.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {r.run_id} · {when(r.created_at)} · {RUN_LABEL[r.status] ?? r.status} · {r.completed_count.toLocaleString()} fetched, {r.failed_count.toLocaleString()} failed of{" "}
              {r.company_count.toLocaleString()} {r.company_count === 1 ? "company" : "companies"}
            </option>
          ))}
        </select>
      </label>
      <p className="help-text">Choose a run to see its status again, for example after a reload or a visit to another page.</p>
      {runsError && <p className="error-text">Fetch runs could not be loaded ({runsError}).</p>}

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
                  <th>{keyHead}</th>
                  <th>Status</th>
                  <th>Annual report</th>
                  <th>Facts</th>
                </tr>
              </thead>
              <tbody>
                {results.results.length + failed.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      {inProgress(manifest) ? "Waiting for the first company…" : "No companies were processed."}
                    </td>
                  </tr>
                )}
                {results.results.map((r) => (
                  <tr key={r._key}>
                    <td data-label="Company">{r.company_id}</td>
                    <td data-label={keyLabel(r.market)} className="mono">{r.market ? (r.cik ?? "") : ""}</td>
                    <td data-label="Status">
                      {statusText(r.status, r.market ?? undefined)}
                      {(r.status === "unrouted" || r.status === "no_source") && r.note && <span className="xbrl-sub"> {r.note}</span>}
                    </td>
                    <td data-label="Annual report">{reportText(r.report)}</td>
                    <td data-label="Facts" className="mono">{r.fact_count.toLocaleString()}</td>
                  </tr>
                ))}
                {failed.map((f) => (
                  <tr key={f.key}>
                    <td data-label="Company">{f.key}</td>
                    <td data-label={keyHead} />
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
            <>
              <button className="secondary" onClick={retryFailed} disabled={busy}>
                Retry
              </button>
              <p className="help-text">Retry resumes this run: companies that already succeeded are skipped.</p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
