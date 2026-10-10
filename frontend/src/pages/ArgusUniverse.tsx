import { useState } from "react";
import { api } from "../api/client";
import { UniversePicker } from "../components/UniversePicker";
import { handoverName, mappingText, routeText, selectedCompanies } from "../lib/workbench";
import type { WorkbenchResponse, WorkbenchRow } from "../types";

type Target = "extraction" | "xbrl";

const ids = (r: WorkbenchRow) =>
  (["LEI", "CIK", "ISIN"] as const).flatMap((k) => (r.mapping.identifiers[k] ?? []).map((v) => `${k} ${v}`));
const when = (s: string | null) => (s ? s.slice(0, 10) : "");

/** Argus universe: one table per saved universe showing, per company, how it maps to the identifier master, which XBRL source it suggests and what is already stored. It never starts a run; it hands the (selected) companies to Extraction or XBRL facts. */
export function ArgusUniverse({ onSendUniverse }: { onSendUniverse: (to: Target, path: string, count: number) => void }) {
  const [path, setPath] = useState("");
  const [data, setData] = useState<WorkbenchResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [scope, setScope] = useState<"all" | "selected">("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load(p: string) {
    setPath(p);
    setData(null);
    setSelected(new Set());
    setScope("all");
    setError("");
    setBusy(true);
    try {
      setData(await api.universeWorkbench({ universe_path: p }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function send(target: Target) {
    if (!data) return;
    setBusy(true);
    setError("");
    try {
      if (scope === "all") return onSendUniverse(target, path, data.rows.length);
      const companies = selectedCompanies(data.rows, selected);
      const saved = await api.universeFromCompanies(companies, handoverName(target));
      onSendUniverse(target, saved.path, saved.company_count);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const rows = data?.rows ?? [];
  const allOn = rows.length > 0 && rows.every((r) => selected.has(r.company.company_id));
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (!n.delete(id)) n.add(id);
      return n;
    });
  const c = data?.counts;
  const none = scope === "selected" && selected.size === 0;

  return (
    <div className="page">
      <h1>Universe</h1>
      <p className="help-text">
        Load a company universe to see how each company maps to the identifier master, which XBRL source fits it, and
        what is already stored. Nothing here starts a run: send the universe on when you are ready.
      </p>
      <section className="card">
        <UniversePicker onResolved={load} />
      </section>
      {busy && !data && <p className="muted">Loading…</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
      {data && c && (
        <section className="card" aria-labelledby="universe-table-title">
          <h2 id="universe-table-title">{rows.length.toLocaleString()} companies</h2>
          <p className="help-text">
            Routes: {c.routes.sec} US (SEC), {c.routes.esef} EU (ESEF), {c.routes.no_source} no XBRL source yet,{" "}
            {c.routes.unrouted} not routed. Mapping: {c.mapping.mapped} mapped, {c.mapping.ambiguous} ambiguous,{" "}
            {c.mapping.unmapped} not in the master, {c.mapping.no_identifier} without identifier.
          </p>
          <div className="row-actions">
            <fieldset className="row-actions" style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="visually-hidden">Scope</legend>
              <label>
                <input type="radio" name="universe-scope" checked={scope === "all"} onChange={() => setScope("all")} /> Whole universe
              </label>
              <label>
                <input type="radio" name="universe-scope" checked={scope === "selected"} onChange={() => setScope("selected")} /> Selected ({selected.size})
              </label>
            </fieldset>
            <button type="button" disabled={busy || none} onClick={() => send("extraction")}>Extraction</button>
            <button type="button" disabled={busy || none} onClick={() => send("xbrl")}>XBRL facts</button>
          </div>
          <div className="table-wrap">
            <table className="data-table stack-on-phone">
              <caption className="visually-hidden">Companies in the universe with mapping, suggested route and availability</caption>
              <thead>
                <tr>
                  <th scope="col">
                    <input
                      type="checkbox"
                      aria-label="Select all companies"
                      checked={allOn}
                      onChange={() => setSelected(allOn ? new Set() : new Set(rows.map((r) => r.company.company_id)))}
                    />
                  </th>
                  <th scope="col">Company</th>
                  <th scope="col">Mapping</th>
                  <th scope="col">Master identifiers</th>
                  <th scope="col">Suggested route</th>
                  <th scope="col">Identity</th>
                  <th scope="col">Documents</th>
                  <th scope="col">Extraction</th>
                  <th scope="col">XBRL</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const a = r.availability;
                  const id = r.company.company_id;
                  return (
                    <tr key={`${id}-${i}`}>
                      <td>
                        <input type="checkbox" aria-label={`Select ${r.company.name || id}`} checked={selected.has(id)} onChange={() => toggle(id)} />
                      </td>
                      <th scope="row" data-label="Company">
                        <span className="xbrl-name">{r.company.name || id}</span>
                        <span className="xbrl-sub mono">{id}</span>
                      </th>
                      <td data-label="Mapping">
                        {mappingText(r.mapping)}
                        {r.mapping.issuer_key && <span className="xbrl-sub mono">{r.mapping.issuer_key}</span>}
                      </td>
                      <td data-label="Identifiers" className="mono">
                        {ids(r).map((x) => <span key={x} className="xbrl-sub">{x}</span>)}
                      </td>
                      <td data-label="Route">
                        {routeText(r.route)}
                        {r.route.detail && <span className="xbrl-sub">{r.route.detail}</span>}
                      </td>
                      <td data-label="Identity">{a.identity ? a.identity.verdict : ""}</td>
                      <td data-label="Documents">
                        {a.documents.registered > 0 && (
                          <>
                            {a.documents.registered} registered
                            <span className="xbrl-sub">{a.documents.parsed} parsed, {a.documents.on_disk} on disk</span>
                          </>
                        )}
                      </td>
                      <td data-label="Extraction">
                        {a.extraction.runs > 0 && (
                          <>
                            {a.extraction.runs} {a.extraction.runs === 1 ? "run" : "runs"}
                            <span className="xbrl-sub">{when(a.extraction.last_run_at)}</span>
                          </>
                        )}
                      </td>
                      <td data-label="XBRL">
                        {a.xbrl && (
                          <>
                            {a.xbrl.fact_count.toLocaleString()} facts
                            <span className="xbrl-sub">{when(a.xbrl.fetched_at)}</span>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
