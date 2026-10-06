import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { announce } from "../lib/announce";
import { parseIntakeError, rowErrorText } from "../lib/holdings";
import type { RowError, SecurityMasterStatus, UnmatchedSecurity } from "../types";

/** Data Hub's golden source: the security master maps every security (and issuer identifier) to one internal issuer
 * id, and every screen reads that map. Matching is exact; a security the master doesn't know stays unmatched and is
 * listed here, to be fixed in the master -- never by hand elsewhere. */
export function SecurityMaster() {
  const [status, setStatus] = useState<SecurityMasterStatus | null>(null);
  const [unmatched, setUnmatched] = useState<UnmatchedSecurity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<RowError[]>([]);

  const load = () => {
    api.securityMasterStatus().then(setStatus, (e: Error) => setError(e.message));
    api.unmatchedSecurities().then((r) => setUnmatched(r.rows), (e: Error) => setError(e.message));
  };
  useEffect(load, []);

  async function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setNotice(null);
    setRowErrors([]);
    setError(null);
    try {
      const r = await api.uploadSecurityMaster(file);
      const msg = `Security master replaced: ${r.identifiers} identifiers for ${r.issuers} issuers. Reload holdings to re-map them.`;
      setNotice(msg);
      announce(msg);
    } catch (err) {
      const parsed = parseIntakeError(err as Error);
      setError(parsed.message);
      setRowErrors(parsed.errors);
    } finally {
      setBusy(false);
      load();
    }
  }

  const ids = status ? Object.entries(status.identifiers).filter(([, n]) => n > 0) : [];

  return (
    <div className="page">
      <h1>Security Master</h1>
      <p className="help-text">
        The golden source for the whole tool: each security and issuer identifier maps to one internal issuer id, by
        exact match only. Holdings, Risk Monitoring, StewardIQ and Argus all read this map. A security it doesn&apos;t
        know is listed below as unmatched; fix it in the master and load it again.
      </p>
      {error && <p className="error-text" role="alert">{error}</p>}
      {rowErrors.length > 0 && (
        <ul className="error-text">
          {rowErrors.slice(0, 50).map((x, i) => <li key={i}>{rowErrorText(x)}</li>)}
          {rowErrors.length > 50 && <li>…and {rowErrors.length - 50} more</li>}
        </ul>
      )}
      {notice && <p role="status">{notice}</p>}

      <section className="card">
        <h2>Current master</h2>
        {!status ? (
          <p className="status-text">Loading…</p>
        ) : status.issuers === 0 ? (
          <p className="help-text">No security master loaded yet: every holding is unmatched until one is.</p>
        ) : (
          <p>
            <strong>{status.issuers}</strong> issuers · {ids.map(([s, n]) => `${n} ${s}`).join(" · ")}
          </p>
        )}
        {status?.last_load && (
          <p className="muted">
            Last load {new Date(status.last_load.at).toLocaleString()}: {status.last_load.status === "ok" ? "loaded" : "rejected"}, {status.last_load.detail}
          </p>
        )}
      </section>

      <section className="card">
        <h2>Load a new master</h2>
        <p className="help-text">
          CSV or Excel with columns <code>issuer_id</code> (your internal id, required), <code>issuer_name</code>, any of{" "}
          <code>isin</code>, <code>cusip</code>, <code>sedol</code>, <code>figi</code>, <code>lei</code>, <code>cik</code>, <code>permid</code> (Refinitiv; ties news to the issuer), and
          optional <code>valid_from</code>/<code>valid_to</code> dates. The file replaces the whole master; the previous one
          is archived. Any invalid row, or one identifier on two issuers at once, rejects the file. Approvers only.{" "}
          <a href={api.securityMasterTemplateUrl()}>Template</a>
        </p>
        <form className="inline-fields" onSubmit={(e) => void upload(e)}>
          <input type="file" accept=".csv,.xlsx" aria-label="Security master file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <button type="submit" disabled={!file || busy}>{busy ? "Loading…" : "Load master"}</button>
        </form>
      </section>

      <section className="card">
        <h2>Unmatched securities {unmatched && `(${unmatched.length})`}</h2>
        <p className="help-text">Held in a latest snapshot, but not mapped to exactly one issuer by the current master.</p>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>ISIN</th><th>Held by</th><th>As of</th><th>Reason</th></tr>
            </thead>
            <tbody>
              {unmatched?.length === 0 && <tr><td colSpan={4} className="muted">Every held security is matched.</td></tr>}
              {unmatched?.map((r) => (
                <tr key={`${r.kind}/${r.holder_id}/${r.security_id}`}>
                  <td>{r.isin ?? r.security_id}</td>
                  <td>{r.holder_id} ({r.kind})</td>
                  <td>{r.as_of}</td>
                  <td>{r.reason}{r.candidates.length > 0 && `: ${r.candidates.join(", ")}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
