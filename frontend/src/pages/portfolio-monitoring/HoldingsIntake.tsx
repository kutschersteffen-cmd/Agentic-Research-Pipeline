import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { FileLink } from "../../components/FileLink";
import { announce } from "../../lib/announce";
import { ResolutionReviewPanel } from "./ResolutionReviewPanel";
import { ageLabel, needsOverrideReason, parseIntakeError, rowErrorText } from "../../lib/holdings";
import type { HolderStatus, IntakeResult, RowError } from "../../types";

const KINDS = ["index", "portfolio"] as const;
const FORMATS = ["csv", "xlsx"] as const;

const summary = (r: IntakeResult): string =>
  [r.status === "unchanged" ? "No change" : `Revision ${r.revision} written (${r.rows} rows)`, r.unresolved.length ? `${r.unresolved.length} ISINs sent to review` : ""]
    .filter(Boolean)
    .join("; ");

/** Holdings intake (E77): holder staleness, template downloads and the file upload. All server text is rendered as text. */
export function HoldingsIntake() {
  const [holders, setHolders] = useState<HolderStatus[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pulling, setPulling] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [kind, setKind] = useState<(typeof KINDS)[number]>("portfolio");
  const [holderId, setHolderId] = useState("");
  const [asOf, setAsOf] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [provider, setProvider] = useState("default");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; errors: RowError[] } | null>(null);
  const reasonRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = () => api.listHolders().then((r) => setHolders(r.holders), (e: Error) => setLoadError(e.message));
  useEffect(() => {
    void load();
  }, []);

  async function pull(h: HolderStatus) {
    setPulling(h.holder_id);
    setNotice(null);
    try {
      const msg = summary(await api.pullHolder(h.kind, h.holder_id));
      setNotice(msg);
      announce(msg);
    } catch (err) {
      const msg = parseIntakeError(err as Error).message;
      setNotice(msg);
      announce(msg);
    } finally {
      setPulling(null);
      void load();
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const msg = summary(await api.uploadHoldings({ file, holder_id: holderId.trim(), kind, as_of: asOf, provider, override_reason: reason.trim() || undefined }));
      setNotice(msg);
      announce(msg);
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      setReason("");
      void load();
    } catch (err) {
      const parsed = parseIntakeError(err as Error);
      setError(parsed);
      if (needsOverrideReason(err as Error)) reasonRef.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Holdings Intake</h2>
      {loadError && <p className="error-text" role="alert">{loadError}</p>}
      <table className="data-table">
        <thead>
          <tr>
            <th>Holder</th><th>Kind</th><th>Source</th><th>As of</th><th>Age</th><th>Last pull</th><th>Status</th><th />
          </tr>
        </thead>
        <tbody>
          {holders.length === 0 && (
            <tr><td colSpan={8} className="muted">No holders yet. Upload a file to create one.</td></tr>
          )}
          {holders.map((h) => (
            <tr key={`${h.kind}/${h.holder_id}`}>
              <td>{h.name || h.holder_id}</td>
              <td>{h.kind}</td>
              <td>{h.source}</td>
              <td>{h.as_of ?? "—"}</td>
              <td>{ageLabel(h.age_days)}</td>
              <td>{h.last_pull_at ? new Date(h.last_pull_at).toLocaleString() : "—"}</td>
              <td>
                <span className={h.stale ? "badge badge-high" : "badge"} title={h.last_error ?? undefined}>{h.stale ? "Stale" : "Current"}</span>
              </td>
              <td>
                {h.source === "api" && (
                  <button className="secondary" onClick={() => void pull(h)} disabled={pulling !== null}>
                    {pulling === h.holder_id ? "Pulling…" : "Pull now"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <ResolutionReviewPanel />

      <h3>Templates</h3>
      <p>
        {KINDS.flatMap((k) =>
          FORMATS.map((f) => (
            <span key={`${k}${f}`}>
              <FileLink url={api.holdingsTemplateUrl(k, f)} name={`holdings-template-${k}.${f}`}>
                {k} template (.{f})
              </FileLink>{" "}
            </span>
          )),
        )}
      </p>

      <h3>Upload holdings</h3>
      <form className="inline-fields" onSubmit={(e) => void submit(e)}>
        <label className="field-label">
          Kind
          <select value={kind} onChange={(e) => setKind(e.target.value as (typeof KINDS)[number])}>
            {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
        <label className="field-label">
          Holder id
          <input value={holderId} onChange={(e) => setHolderId(e.target.value)} required />
        </label>
        <label className="field-label">
          As of
          <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} required />
        </label>
        <label className="field-label">
          File
          <input ref={fileRef} type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
        </label>
        <label className="field-label">
          Provider
          <input value={provider} onChange={(e) => setProvider(e.target.value)} />
        </label>
        <label className="field-label">
          Override reason (optional)
          <input ref={reasonRef} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <button type="submit" disabled={busy || !file || !holderId.trim() || !asOf}>{busy ? "Uploading…" : "Upload"}</button>
      </form>
      {notice && <p role="status">{notice}</p>}
      {error && (
        <div className="error-text" role="alert">
          <p>{error.message}</p>
          {error.errors.length > 0 && (
            <ul>{error.errors.map((x, i) => <li key={i}>{rowErrorText(x)}</li>)}</ul>
          )}
        </div>
      )}
    </section>
  );
}
