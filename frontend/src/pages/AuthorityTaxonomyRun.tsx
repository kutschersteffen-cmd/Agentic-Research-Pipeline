import { useEffect, useState } from "react";
import { api } from "../api/client";
import {
  CHECKLIST_KEYS, THEME_KEYS, canBuild, initialSelection, prefill, sourcesBody, startBody, startPolling, viewFor,
  type Selection, type StartForm,
} from "../lib/authorityTaxonomy";
import type { AuthorityRunState } from "../types";
import { AuthorityDraftReview } from "./AuthorityDraftReview";

const BASE = "#/taxonomy/authority";
const EMPTY: StartForm = { theme_name: "", theme_key: null, scope: "", guidance: "", value_chain: false };
let nextForm: StartForm | null = null; // "Start a new run" hands its inputs to the next start form

const message = (e: unknown) => (e as Error).message.replace(/^\d+: /, "");

function StartFormView() {
  const [form, setForm] = useState<StartForm>(() => {
    const f = nextForm ?? EMPTY;
    nextForm = null;
    return f;
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<StartForm>) => setForm({ ...form, ...patch });

  async function start() {
    const out = startBody(form);
    if ("error" in out) return setError(out.error);
    setBusy(true);
    setError(null);
    try {
      const { id } = await api.startAuthorityRun(out.body);
      window.location.hash = `${BASE}/${id}`;
    } catch (e) {
      setError(message(e));
      setBusy(false);
    }
  }

  return (
    <div>
      <h2>Build from authority sources</h2>
      <label>Theme name<input value={form.theme_name} onChange={(e) => set({ theme_name: e.target.value })} /></label>
      {error && <p className="error-text" role="alert">{error}</p>}
      <label>
        Theme key
        <select value={form.theme_key ?? ""} onChange={(e) => set({ theme_key: e.target.value || null })}>
          <option value="">None</option>
          {THEME_KEYS.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
        </select>
      </label>
      <label>Scope<textarea value={form.scope} onChange={(e) => set({ scope: e.target.value })} /></label>
      <label>Source guidance<textarea value={form.guidance} onChange={(e) => set({ guidance: e.target.value })} /></label>
      <label className="checkbox-label">
        <input type="checkbox" checked={form.value_chain} onChange={(e) => set({ value_chain: e.target.checked })} />
        Value chain
      </label>
      <button disabled={busy} onClick={start}>Start</button>
    </div>
  );
}

function Sources({ run, onRun }: { run: AuthorityRunState; onRun: (r: AuthorityRunState) => void }) {
  const [sel, setSel] = useState<Selection>(() => initialSelection(run));
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(run.error ?? null);
  const [busy, setBusy] = useState(false);

  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      if ((e as Error).message.startsWith("409")) onRun(await api.getAuthorityRun(run.run_id));
      else setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function upload(files: FileList | null) {
    for (const f of Array.from(files ?? [])) {
      setSel((s) => ({ ...s, uploading: s.uploading + 1 }));
      try {
        const { path } = await api.uploadAuthorityDocument(f);
        setSel((s) => ({ ...s, uploading: s.uploading - 1, files: [...s.files, { name: f.name, path }] }));
      } catch (e) {
        setSel((s) => ({ ...s, uploading: s.uploading - 1 }));
        setError(`${f.name}: ${message(e)}`);
      }
    }
  }

  const toggle = (u: string) => setSel((s) => ({ ...s, ticked: s.ticked.includes(u) ? s.ticked.filter((x) => x !== u) : [...s.ticked, u] }));

  return (
    <div>
      <h2>Choose sources for {run.theme_name}</h2>
      {error && <p className="error-text" role="alert">{error}</p>}
      <ul className="plain-list">
        {run.candidates.map((c) => (
          <li key={c.url} className="card">
            <label className="checkbox-label">
              <input type="checkbox" checked={sel.ticked.includes(c.url)} onChange={() => toggle(c.url)} aria-label={`Select ${c.title}`} />
              <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a>
            </label>{" "}
            <span className="muted">{c.source_type.replace(/_/g, " ")}</span>
            {c.from_library && <span className="badge">From library</span>}
            {!c.fetchable && <span className="error-text"> Not fetchable</span>}
            <p>{c.summary}</p>
            <p className="muted">{c.reason}</p>
            <div aria-label="Checklist coverage">
              {CHECKLIST_KEYS.map((k) => (
                <span key={k} className="chip" data-covered={c.covers.includes(k)} title={c.covers.includes(k) ? "covered" : "not covered"}>
                  {c.covers.includes(k) ? "✓ " : ""}{k}
                </span>
              ))}
            </div>
          </li>
        ))}
      </ul>
      <h3>Add URL</h3>
      <input aria-label="URL" value={url} onChange={(e) => setUrl(e.target.value)} />
      <button disabled={!url.trim() || sel.urls.includes(url.trim())} onClick={() => { setSel((s) => ({ ...s, urls: [...s.urls, url.trim()] })); setUrl(""); }}>Add URL</button>
      <ul className="plain-list">
        {sel.urls.map((u) => <li key={u}>{u} <button aria-label={`Remove ${u}`} onClick={() => setSel((s) => ({ ...s, urls: s.urls.filter((x) => x !== u) }))}>Remove</button></li>)}
      </ul>
      <h3>Upload document</h3>
      <input type="file" aria-label="Upload document" accept=".pdf,.txt,.md" multiple onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} />
      <ul className="plain-list">
        {sel.files.map((f) => <li key={f.path}>{f.name} <button aria-label={`Remove ${f.name}`} onClick={() => setSel((s) => ({ ...s, files: s.files.filter((x) => x.path !== f.path) }))}>Remove</button></li>)}
      </ul>
      <button disabled={busy || !canBuild(sel)} onClick={() => act(async () => onRun(await api.selectAuthoritySources(run.run_id, sourcesBody(sel))))}>Build draft</button>
    </div>
  );
}

function Ended({ run }: { run: AuthorityRunState }) {
  return (
    <div>
      <p>{run.stage === "failed" ? `The run for ${run.theme_name} failed.` : `The run for ${run.theme_name} was cancelled.`}</p>
      {run.error && <p className="error-text">{run.error}</p>}
      <button onClick={() => { nextForm = prefill(run); window.location.hash = BASE; }}>Start a new run</button>
    </div>
  );
}

export function AuthorityTaxonomyRun({ runId }: { runId?: string }) {
  const [run, setRun] = useState<AuthorityRunState | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    if (!runId) return;
    return startPolling(
      () => api.getAuthorityRun(runId), setRun, document,
      (e) => ((e as Error).message.startsWith("404") ? setMissing(true) : setError(message(e))),
    );
  }, [runId]);

  if (!runId) return <div className="page"><StartFormView /></div>;
  const view = missing ? "not_found" : run ? viewFor(run) : null;
  return (
    <div className="page">
      <p><a href="#/taxonomy">Taxonomy Library</a></p>
      {error && <p className="error-text" role="alert">{error}</p>}
      {view === null && !error && <p className="muted">Loading…</p>}
      {view === "not_found" && <p>Run not found. <a href={BASE}>Start a new run</a></p>}
      {run && view === "working" && (
        <div>
          <p role="status">{run.stage === "discovering" ? `Looking for authority sources for ${run.theme_name}…` : `Reading the selected sources for ${run.theme_name} and drafting the taxonomy…`}</p>
          <button disabled={cancelling} onClick={async () => {
            setCancelling(true);
            try { await api.cancelAuthorityRun(run.run_id); setRun(await api.getAuthorityRun(run.run_id)); } catch (e) { setError(message(e)); } finally { setCancelling(false); }
          }}>Cancel</button>
        </div>
      )}
      {run && view === "sources" && <Sources key={`${run.run_id}-${run.error ?? ""}-${run.candidates.length}`} run={run} onRun={setRun} />}
      {run && view === "review" && run.draft && <AuthorityDraftReview key={run.run_id} run={run} onRun={setRun} />}
      {run && view === "accepted" && (
        <p>Accepted as taxonomy {run.taxonomy_id}. <a href="#/taxonomy">Open the Taxonomy Library</a></p>
      )}
      {run && view === "ended" && <Ended run={run} />}
    </div>
  );
}
