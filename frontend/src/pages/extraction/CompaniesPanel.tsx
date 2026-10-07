import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { UniversePicker } from "../../components/UniversePicker";
import { when } from "../../lib/runs";
import type { FlowAction, FlowState, StageOutput } from "../../lib/stagedFlow";
import type { CompanyRef, Readiness, UniverseHandoff } from "../../types";

/** A list share as a saved universe; an empty share needs no file. */
async function share(companies: CompanyRef[], name: string): Promise<StageOutput> {
  if (companies.length === 0) return { path: "", count: 0, companies: [] };
  const res = await api.universeFromCompanies(companies, name);
  return { path: res.path, count: res.company_count, companies };
}

/** Batch upload or one typed-in company, the TNFD period, and the ready / to-onboard split. */
export function CompaniesPanel({
  flow,
  dispatch,
  pendingUniverse,
  tnfd,
  asOf,
  onAsOf,
}: {
  flow: FlowState;
  dispatch: (a: FlowAction) => void;
  pendingUniverse?: UniverseHandoff | null;
  tnfd: boolean;
  asOf: string;
  onAsOf: (v: string) => void;
}) {
  const [scope, setScope] = useState<"batch" | "single">("batch");
  const [single, setSingle] = useState({ name: "", ticker: "", website: "" });
  const [busy, setBusy] = useState(false);
  const [readyOpen, setReadyOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [readyRows, setReadyRows] = useState<(CompanyRef & { readiness: Readiness })[]>([]);

  /** One company typed in; its id is the ticker, or the name when there is none. */
  const singleCompany: CompanyRef | null = single.name.trim()
    ? {
        company_id: (single.ticker.trim() || single.name.trim()).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, ""),
        name: single.name.trim(),
        ticker: single.ticker.trim() || null,
        website: single.website.trim() || null,
      }
    : null;

  async function confirmSingle() {
    if (!singleCompany) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.universeFromCompanies([singleCompany], "single");
      dispatch({ type: "companies", output: { path: res.path, count: res.company_count, companies: [singleCompany] } });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Readiness runs once per company list: every `companies` dispatch makes a new object, nothing else does.
  const list = flow.companies;
  useEffect(() => {
    setReadyRows([]);
    if (!list) return;
    let live = true;
    (async () => {
      try {
        const res = await api.documentReadiness(list.companies ? { companies: list.companies } : { universe_path: list.path });
        const strip = res.ready.map(({ readiness: _r, ...c }) => c);
        const [ready, onboard] = await Promise.all([share(strip, "ready"), share(res.onboard, "onboard")]);
        if (!live) return;
        setReadyRows(res.ready);
        dispatch({ type: "readiness", ready, onboard });
      } catch {
        if (live) dispatch({ type: "readiness", ready: null, onboard: null });
      }
    })();
    return () => {
      live = false;
    };
  }, [list, dispatch]);

  const checking = !!flow.companies && !flow.ready && !flow.onboard && !flow.readinessNote;

  return (
    <section className="card">
      <h2>Choose the companies</h2>
      <div className="view-toggle" role="group" aria-label="Run on">
        <button className={scope === "batch" ? "active" : ""} aria-pressed={scope === "batch"} onClick={() => setScope("batch")}>
          Batch (list)
        </button>
        <button className={scope === "single" ? "active" : ""} aria-pressed={scope === "single"} onClick={() => setScope("single")}>
          Single company
        </button>
      </div>
      {scope === "batch" && pendingUniverse && flow.companies?.path === pendingUniverse.path && (
        <p className="status-text">
          Using {pendingUniverse.count} companies sent from {pendingUniverse.from}. Upload a different universe below to replace it.
        </p>
      )}
      {tnfd && (
        <label className="field-label">
          Reporting period
          <input value={asOf} onChange={(e) => onAsOf(e.target.value)} placeholder="FY2025" />
        </label>
      )}
      <div hidden={scope !== "batch"}>
        <UniversePicker onResolved={(path, count) => dispatch({ type: "companies", output: { path, count } })} />
      </div>
      <div hidden={scope !== "single"}>
        <div className="inline-fields">
          <label className="field-label">
            Company name
            <input value={single.name} onChange={(e) => setSingle({ ...single, name: e.target.value })} placeholder="BASF SE" />
          </label>
          <label className="field-label">
            Ticker (optional)
            <input value={single.ticker} onChange={(e) => setSingle({ ...single, ticker: e.target.value })} placeholder="BAS" />
          </label>
          <label className="field-label">
            Website (optional)
            <input value={single.website} onChange={(e) => setSingle({ ...single, website: e.target.value })} placeholder="basf.com" />
          </label>
        </div>
        <button onClick={confirmSingle} disabled={busy || !singleCompany}>
          {busy ? "Saving…" : "Use this company"}
        </button>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}

      {flow.companies && (
        <>
          <p className="status-text" role="status">
            {"✓"} {flow.companies.companies?.length === 1 ? flow.companies.companies[0].name : `${flow.companies.count} companies`} selected
            {checking ? " · checking stored documents…" : ` · ${flow.ready?.count ?? 0} ready · ${flow.onboard?.count ?? 0} to onboard`}
          </p>
          {flow.readinessNote && <p className="await-text">{flow.readinessNote}</p>}
          <label className="checkbox-label">
            <input type="checkbox" checked={flow.recheckReady} onChange={(e) => dispatch({ type: "recheckReady", on: e.target.checked })} />
            Re-check ready companies too
          </label>
          {readyRows.length > 0 && (
            <details onToggle={(e) => setReadyOpen(e.currentTarget.open)}>
              <summary>Ready companies ({readyRows.length})</summary>
              {readyOpen && <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Company</th>
                      <th>Document types</th>
                      <th>Parsed / registered</th>
                      <th>Last seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {readyRows.map((c) => (
                      <tr key={c.company_id}>
                        <td>{c.name}</td>
                        <td>{c.readiness.doc_types.join(", ") || "—"}</td>
                        <td className="mono">
                          {c.readiness.parsed} / {c.readiness.registered}
                        </td>
                        <td className="mono">{c.readiness.last_seen_at ? when(c.readiness.last_seen_at) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>}
            </details>
          )}
          <p className="help-text">Embeddings are reused when cached.</p>
        </>
      )}
    </section>
  );
}
