import { useEffect, useState } from "react";
import { api } from "../api/client";
import { TagCombobox } from "../components/TagCombobox";
import { UniversePicker } from "../components/UniversePicker";
import { reportText, statusText } from "../lib/xbrlTags";
import type { RunManifest, XbrlCompanyStatus } from "../types";

type ResultRow = XbrlCompanyStatus & { _key: string };
type ErrorRow = { key: string; error: string };
type Saved = { name: string; tags: string[]; created_at?: string };
type Retry = { keys: string[]; errorsBefore: number; updatedBefore: string };

const POLL_MS = 2500;
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
const tagCount = (n: number) => `${n} ${n === 1 ? "tag" : "tags"}`;

/** XBRL Facts: fetch companies' SEC XBRL facts, choose the tags that matter. Areas stack as sections. */
export function XbrlFacts() {
  const [tags, setTags] = useState<string[]>([]);
  return (
    <div className="page">
      <h1>XBRL Facts</h1>
      <p className="help-text">
        Download each company’s XBRL facts and annual report from the SEC, keep every fact traceable to its filing, and
        choose which tags you need.
      </p>
      <FetchArea tags={tags} />
      <TagsArea tags={tags} onChange={setTags} />
    </div>
  );
}

/** A retry re-runs the failed companies inside the same run, and the backend leaves the run's status
 * as it was, so the retry is finished once each retried company has a new result or a new error. */
function isFinished(m: RunManifest, results: ResultRow[], errors: ErrorRow[], retry: Retry | null): boolean {
  if (m.status === "pending" || m.status === "running") return false;
  if (!retry) return true;
  if (m.status === "failed" && m.updated_at !== retry.updatedBefore) return true;
  const done = new Set([...results.map((r) => r._key), ...errors.slice(retry.errorsBefore).map((e) => e.key)]);
  return retry.keys.every((k) => done.has(k));
}

function FetchArea({ tags }: { tags: string[] }) {
  const [universe, setUniverse] = useState<{ path: string; count: number } | null>(null);
  const [mode, setMode] = useState<"all" | "selected">("all");
  const [refresh, setRefresh] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [manifest, setManifest] = useState<RunManifest | null>(null);
  const [results, setResults] = useState<{ total: number; results: ResultRow[] }>({ total: 0, results: [] });
  const [errors, setErrors] = useState<ErrorRow[]>([]);
  const [retry, setRetry] = useState<Retry | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let stopped = false;
    let timer: number | undefined;
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
        if (!isFinished(m, r.results, e.errors, retry)) timer = window.setTimeout(tick, POLL_MS);
        else if (retry) setRetry(null);
      } catch (err) {
        if (stopped) return;
        setPollError(msg(err)); // keep trying, slower, in case the backend comes back
        timer = window.setTimeout(tick, POLL_MS * 4);
      }
    };
    tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [runId, retry]);

  const succeeded = new Set(results.results.map((r) => r._key));
  const latestError = new Map(errors.map((e) => [e.key, e.error])); // later rows win
  const failed = [...latestError].filter(([key]) => !succeeded.has(key)).map(([key, error]) => ({ key, error }));
  const finished = manifest !== null && isFinished(manifest, results.results, errors, retry);
  const canRetry = finished && (failed.length > 0 || manifest?.status === "failed");
  const noTags = mode === "selected" && tags.length === 0;

  async function start() {
    if (!universe) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.startXbrlRun({
        universe_path: universe.path,
        tags: mode === "selected" ? tags : undefined,
        refresh,
      });
      setManifest(null);
      setResults({ total: 0, results: [] });
      setErrors([]);
      setRetry(null);
      setRunId(res.run_id);
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
      setRetry({ keys: failed.map((f) => f.key), errorsBefore: errors.length, updatedBefore: manifest.updated_at });
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
      <button onClick={start} disabled={busy || !universe || noTags || (!finished && runId !== null && !pollError)}>
        Start fetch{universe ? ` for ${universe.count.toLocaleString()} companies` : ""}
      </button>
      <div aria-live="polite">{error && <p className="error-text">{error}</p>}</div>

      {runId && (
        <div className="xbrl-run">
          <p className="toolbar" aria-live="polite">
            <span className={`status-pill status-${manifest?.status ?? "pending"}`}>
              {retry ? "Retrying failed companies" : RUN_LABEL[manifest?.status ?? "pending"] ?? manifest?.status}
            </span>
            {manifest && (
              <span className="muted">
                {results.total.toLocaleString()} of {manifest.company_count.toLocaleString()} companies fetched,{" "}
                {failed.length.toLocaleString()} failed
              </span>
            )}
            <span className="muted mono">{runId}</span>
          </p>
          {pollError && <p className="error-text">Run status could not be loaded ({pollError}). Trying again.</p>}
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
                      {finished ? "No companies were processed." : "Waiting for the first company…"}
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

function TagsArea({ tags, onChange }: { tags: string[]; onChange: (next: string[]) => void }) {
  const [name, setName] = useState("");
  const [saved, setSaved] = useState<Saved[] | null>(null);
  const [savedError, setSavedError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [registry, setRegistry] = useState<{ busy: boolean; ok: boolean; text: string } | null>(null);

  const loadSaved = () =>
    api
      .listXbrlSelections()
      .then((rows) => {
        setSaved(rows as Saved[]);
        setSavedError(null);
      })
      .catch((err) => setSavedError(msg(err)));
  useEffect(() => {
    loadSaved();
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaveStatus(null);
    try {
      const res = await api.saveXbrlSelection(name.trim(), tags);
      setSaveStatus({ ok: true, text: `Saved “${res.name}”: ${tagCount(res.tags.length)}, ${res.row_count.toLocaleString()} facts from stored companies.` });
      setName("");
      loadSaved();
    } catch (err) {
      setSaveStatus({ ok: false, text: `Could not save the selection (${msg(err)}).` });
    }
  }

  async function updateRegistry() {
    setRegistry({ busy: true, ok: true, text: "Updating the tag registry from the official taxonomies. This can take a minute…" });
    try {
      const counts = (await api.updateXbrlTaxonomy()) as Record<string, number>;
      const parts = Object.entries(counts).map(([t, n]) => `${t} ${n.toLocaleString()} tags`);
      setRegistry({ busy: false, ok: true, text: `Tag registry updated: ${parts.join(", ")}.` });
    } catch (err) {
      setRegistry({ busy: false, ok: false, text: `Tag registry update failed (${msg(err)}). The previous registry is still in use.` });
    }
  }

  return (
    <section className="card" aria-labelledby="xbrl-tags-title">
      <h2 id="xbrl-tags-title">Tags</h2>
      <TagCombobox selected={tags} onChange={onChange} />

      <form className="inline-fields xbrl-save" onSubmit={save}>
        <label className="field-label" htmlFor="xbrl-selection-name">
          Selection name
        </label>
        <input
          id="xbrl-selection-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-describedby="xbrl-selection-hint"
        />
        <button type="submit" disabled={!name.trim() || tags.length === 0}>
          Save as selection
        </button>
      </form>
      <p className="help-text" id="xbrl-selection-hint">
        Letters, digits, dot, underscore and hyphen, starting with a letter or digit, e.g. revenue-core. Saving cuts these
        tags out of every stored company.
      </p>
      <div aria-live="polite">{saveStatus && <p className={saveStatus.ok ? "status-text" : "error-text"}>{saveStatus.text}</p>}</div>

      <h3>Saved selections</h3>
      {savedError && <p className="error-text">Saved selections could not be loaded ({savedError}).</p>}
      {saved && saved.length === 0 && <p className="muted">No saved selections yet.</p>}
      {saved && saved.length > 0 && (
        <ul className="xbrl-selections">
          {saved.map((s) => (
            <li key={s.name}>
              <span>
                <strong>{s.name}</strong> <span className="muted">{tagCount(s.tags.length)}</span>
              </span>
              <button className="secondary" onClick={() => onChange(s.tags)} aria-label={`Load ${s.name} into the chosen tags`}>
                Load
              </button>
            </li>
          ))}
        </ul>
      )}

      <h3>Tag registry</h3>
      <p className="help-text">Downloads the latest US GAAP, IFRS and DEI taxonomies so every official tag can be chosen.</p>
      <button className="secondary" onClick={updateRegistry} disabled={registry?.busy}>
        Update tag registry
      </button>
      <div aria-live="polite">{registry && <p className={registry.ok ? "status-text" : "error-text"}>{registry.text}</p>}</div>
    </section>
  );
}
