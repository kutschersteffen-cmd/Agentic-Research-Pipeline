import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { InputPicker } from "../components/InputPicker";
import { StepBar } from "../components/StepBar";
import { continueLabel, documentsText, extractedBeforeText, flowHref, identifierList } from "../lib/argusFlow";
import { STEPS } from "../lib/argusStart";
import type { ArgusFlow as Flow } from "../types";

type Target = "extraction";
const EMPTY = { name: "", ticker: "", isin: "", lei: "", cik: "" };

/** #/argus/<flow_id>/<step>: one extraction being set up. The flow lives on the server, so a reload or a teammate's link shows the same step and data. */
export function ArgusFlow({ flowId, step, onSendUniverse }: { flowId: string; step: number; onSendUniverse: (to: Target, path: string, count: number) => void }) {
  const [flow, setFlow] = useState<Flow | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [one, setOne] = useState(EMPTY);
  const [saved, setSaved] = useState("");

  useEffect(() => {
    api.getArgusFlow(flowId).then(setFlow, (e: Error) => (/not found/i.test(e.message) ? setMissing(true) : setError(e.message)));
  }, [flowId]);

  const act = useCallback(async (fn: () => Promise<Flow | void>) => {
    setBusy(true);
    setError("");
    try {
      const f = await fn();
      if (f) setFlow(f);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  if (missing)
    return (
      <div className="page">
        <h1>Argus</h1>
        <p>This extraction does not exist.</p>
        <a href="#/argus">Back to Argus</a>
      </div>
    );
  if (!flow) return <div className="page">{error ? <p className="error-text" role="alert">{error}</p> : <p className="muted" role="status">Loading…</p>}</div>;

  const unmatched = flow.rows.filter((r) => r.problem);
  const unmatchedCompanies = flow.companies.filter((c) => !c.entity_id);
  const n = flow.companies.length;

  return (
    <div className="page argus-flow">
      <h1>New extraction</h1>
      <StepBar flowId={flow.flow_id} current={step} reached={flow.step} />
      {error && <p className="error-text" role="alert">{error}</p>}
      {step !== 1 ? (
        <p>
          {step} {STEPS[step - 1]} is not available here yet. <a href={flowHref(flow.flow_id, 1)}>Back to 1 Companies</a>
        </p>
      ) : (
        <>
          <section className="card argus-add" aria-label="Add companies">
            <label className="field-label">
              Upload a list
              <input
                type="file"
                accept=".csv,.json"
                disabled={busy}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) act(() => api.uploadFlowCompanies(flow.flow_id, file));
                }}
              />
            </label>
            <p className="help-text">CSV or JSON with name and any of lei, isin, cik, ticker, sector, country, company_id.</p>
            <InputPicker
              kind="universe"
              label="Or pick a saved universe"
              value={saved}
              onChange={(o) => {
                setSaved(o?.id ?? "");
                if (o) act(() => api.addFlowCompanies(flow.flow_id, { universe_path: o.id }));
              }}
            />
            <form
              className="argus-one"
              onSubmit={(e) => {
                e.preventDefault();
                const company = Object.fromEntries(Object.entries(one).filter(([, v]) => v.trim())) as typeof one;
                act(async () => {
                  const f = await api.addFlowCompanies(flow.flow_id, { company });
                  setOne(EMPTY);
                  return f;
                });
              }}
            >
              <fieldset>
                <legend>Add one company</legend>
                {(["name", "ticker", "isin", "lei", "cik"] as const).map((k) => (
                  <label key={k} className="field-label">
                    {k === "name" ? "Name" : k.toUpperCase().replace("TICKER", "Ticker")}
                    <input id={`argus-one-${k}`} value={one[k]} required={k === "name"} onChange={(e) => setOne({ ...one, [k]: e.target.value })} />
                  </label>
                ))}
                <button type="submit" disabled={busy}>Add</button>
              </fieldset>
            </form>
          </section>
          <div className="table-wrap">
            <table className="data-table stack-on-phone" aria-label="Companies">
              <thead>
                <tr>
                  <th scope="col">Company</th>
                  <th scope="col">Identifiers</th>
                  <th scope="col">Sector</th>
                  <th scope="col">Country</th>
                  <th scope="col">Extracted before</th>
                  <th scope="col">Documents on file</th>
                </tr>
              </thead>
              <tbody>
                {flow.rows.map((r) => (
                  <tr key={r.central_id ?? r.company_id} className={r.problem ? "argus-row-await" : undefined}>
                    <td data-label="Company">
                      <div>
                        <span className="xbrl-name">{r.name}</span>
                        {r.central_id && <span className="xbrl-sub mono">{r.central_id}</span>}
                        {r.problem && <span className="xbrl-sub await-text">{r.problem}</span>}
                      </div>
                    </td>
                    <td data-label="Identifiers" className="mono">
                      {/* one block, so the identifiers stack inside a phone's label/value row */}
                      {identifierList(r).length > 0 && <div>{identifierList(r).map((x) => <span key={x} className="xbrl-sub">{x}</span>)}</div>}
                    </td>
                    <td data-label="Sector">{r.sector ?? ""}</td>
                    <td data-label="Country">{r.country ?? ""}</td>
                    <td data-label="Extracted before">{extractedBeforeText(r.extracted_before)}</td>
                    <td data-label="Documents on file">{documentsText(r.documents, r.document_types)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {n === 0 && <p className="muted">No companies yet. Upload a list, pick a saved universe or add one company.</p>}
          <div className="row-actions argus-flow-actions">
            {flow.identity_run_id ? (
              <span>
                Identity run started. <a href="#/identity">Open identity runs</a>
              </span>
            ) : (
              unmatched.length > 0 && (
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      const run = await api.startIdentityRun({ companies: unmatchedCompanies });
                      return api.patchArgusFlow(flow.flow_id, { identity_run_id: run.run_id });
                    })
                  }
                >
                  Resolve identities
                </button>
              )
            )}
            <button
              type="button"
              disabled={busy || n === 0}
              onClick={() =>
                act(async () => {
                  // shortcut: hands the list to the old Extraction screen until slice 3 builds step 2
                  const saved = await api.universeFromCompanies(flow.companies, "argus");
                  onSendUniverse("extraction", saved.path, saved.company_count);
                })
              }
            >
              {continueLabel(n)}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
