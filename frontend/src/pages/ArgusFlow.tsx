import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { CompanyFields, CompanyPicker, type OneCompany } from "../components/CompanyPicker";
import { StepBar } from "../components/StepBar";
import { companiesLocked, continueLabel, documentsText, extractedBeforeText, flowHref, identifierList, identityPolls, identityStatus, typedCompany } from "../lib/argusFlow";
import { STEPS } from "../lib/argusStart";
import { errorDetail } from "../lib/barrier";
import { neighbour, useRowFocus } from "../lib/rowFocus";
import { ArgusDocuments } from "./ArgusDocuments";
import { ArgusExtract } from "./ArgusExtract";
import { ArgusResults } from "./ArgusResults";
import { ArgusSchema } from "./ArgusSchema";
import type { ArgusFlow as Flow } from "../types";

/** Step 1: one row's Name, Ticker, ISIN, LEI and CIK, open for a correction. Saving registers the row again. */
function EditCompanyRow({ company, busy, onSave, onCancel }: {
  company: Flow["companies"][number];
  busy: boolean;
  onSave: (company: OneCompany) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({ name: company.name, ticker: company.ticker ?? "", isin: company.isin ?? "", lei: company.lei ?? "", cik: company.cik ?? "" });
  const ref = useRef<HTMLFormElement>(null);
  useEffect(() => ref.current?.querySelector("input")?.focus(), []); // Edit was just removed from under the keyboard's focus
  return (
    <tr>
      <td colSpan={7}>
        <form
          ref={ref}
          className="argus-one"
          aria-label={`Edit ${company.name}`}
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy) onSave(typedCompany(form));
          }}
        >
          <fieldset>
            <legend>Edit {company.name}</legend>
            <CompanyFields value={form} onChange={setForm} />
            {/* aria-disabled, not disabled: a disabled button loses the keyboard's focus, and a Save that fails never gets it back */}
            <button type="submit" aria-disabled={busy}>Save</button>
            <button type="button" className="link-button" onClick={onCancel}>Cancel</button>
          </fieldset>
        </form>
      </td>
    </tr>
  );
}

/** #/argus/<flow_id>/<step>: one extraction being set up. The flow lives on the server, so a reload or a teammate's link shows the same step and data. */
export function ArgusFlow({ flowId, step: urlStep }: { flowId: string; step: number | null }) {
  const [flow, setFlow] = useState<Flow | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // The step 1 row being edited: its position and name, not its company_id, which an identity result can change
  // while the form is open. `opened` is the id it was opened under, the form's key, so what was typed stays.
  const [editing, setEditing] = useState<{ row: number; name: string; opened: string } | null>(null);
  const [companiesTable, focusRow] = useRowFocus();
  // a step the URL names that is not 1 to 5 (/7, /2.5): shown as, and sent to, the flow's furthest step
  const step = urlStep ?? flow?.step ?? 1;
  useEffect(() => {
    if (urlStep === null && flow) window.location.replace(flowHref(flowId, flow.step));
  }, [urlStep, flow, flowId]);

  // Read again on every step change: a run that finished on step 4 changes what step 3 must show (the repeat
  // warning), and a stale flow let Start through to a 400 that named a list not on screen.
  useEffect(() => {
    api.getArgusFlow(flowId).then(setFlow, (e: Error) => (/not found/i.test(e.message) ? setMissing(true) : setError(errorDetail(e))));
  }, [flowId, urlStep]);

  // bumped at the start and end of every change, so a background read that began before it is dropped
  const changes = useRef(0);
  const act = useCallback(async (fn: () => Promise<Flow | void>) => {
    changes.current++;
    setBusy(true);
    setError("");
    try {
      const f = await fn();
      if (f) setFlow(f);
      return true;
    } catch (e) {
      setError(errorDetail(e as Error));
      return false;
    } finally {
      changes.current++;
      setBusy(false);
    }
  }, []);
  const refresh = useCallback(() => {
    const at = changes.current;
    api.getArgusFlow(flowId).then((f) => at === changes.current && setFlow(f), () => {}); // a failed poll just waits for the next
  }, [flowId]);
  // an identity run's result is applied on the server when the flow is read after the run has ended
  const identityRuns = identityPolls(flow?.identity?.status);
  useEffect(() => {
    if (step !== 1 || !identityRuns) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [step, identityRuns, refresh]);

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
  const identity = identityStatus(flow.identity_run_id, flow.identity?.status ?? null, unmatched.length);
  const unmatchedCompanies = flow.companies.filter((c) => !c.entity_id);
  const n = flow.companies.length;
  const locked = companiesLocked(flow);

  return (
    <div className="page argus-flow">
      <h1>New extraction</h1>
      <StepBar flowId={flow.flow_id} current={step} reached={flow.step} />
      {error && <p className="error-text" role="alert">{error}</p>}
      {step === 2 ? (
        <ArgusDocuments
          flow={flow}
          busy={busy}
          act={act}
          refresh={refresh}
          onContinue={() =>
            act(async () => {
              const f = await api.patchArgusFlow(flow.flow_id, { step: 3 });
              window.location.hash = flowHref(flow.flow_id, 3);
              return f;
            })
          }
        />
      ) : step === 3 ? (
        <ArgusSchema flow={flow} busy={busy} act={act} />
      ) : step === 4 || step === 5 ? (
        flow.run_id ? (
          step === 4 ? <ArgusExtract flow={flow} onEnded={refresh} /> : <ArgusResults flow={flow} />
        ) : (
          <p>
            Nothing has started yet. <a href={flowHref(flow.flow_id, 3)}>Back to 3 {STEPS[2]}</a>
          </p>
        )
      ) : (
        <>
          <CompanyPicker
            busy={busy}
            onUpload={(file) => act(() => api.uploadFlowCompanies(flow.flow_id, file))}
            onUniverse={(path) => act(() => api.addFlowCompanies(flow.flow_id, { universe_path: path }))}
            onAddOne={(company) => act(() => api.addFlowCompanies(flow.flow_id, { company }))}
          />
          <div className="table-wrap">
            <table ref={companiesTable} tabIndex={-1} className="data-table stack-on-phone argus-companies" aria-label="Companies">
              <thead>
                <tr>
                  <th scope="col">Company</th>
                  <th scope="col">Identifiers</th>
                  <th scope="col">Sector</th>
                  <th scope="col">Country</th>
                  <th scope="col">Extracted before</th>
                  <th scope="col">Documents on file</th>
                  {!locked && <th scope="col"><span className="visually-hidden">Actions</span></th>}
                </tr>
              </thead>
              <tbody>
                {flow.rows.map((r, i) => !locked && editing?.row === i && editing.name === r.name ? (
                  <EditCompanyRow
                    key={`edit:${editing.opened}`}
                    company={flow.companies.find((c) => c.company_id === r.company_id)!}
                    busy={busy}
                    onCancel={() => (setEditing(null), focusRow(r.company_id))}
                    onSave={async (company) => {
                      if (!(await act(() => api.updateFlowCompany(flow.flow_id, r.company_id, company)))) return;
                      setEditing(null);
                      focusRow(r.company_id); // a row whose key the edit changed is not found: the table takes focus
                    }}
                  />
                ) : (
                  <tr key={r.company_id} data-row={r.company_id} className={r.problem ? "argus-row-await" : undefined}>
                    <td data-label="Company">
                      <div>
                        <span className="xbrl-name">{r.name}</span>
                        {r.central_id && <span className="xbrl-sub mono">Central ID {r.central_id}</span>}
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
                    {!locked && (
                      <td>
                        <span className="row-actions">
                          <button type="button" className="link-button" aria-label={`Edit ${r.name}`} disabled={busy} onClick={() => setEditing({ row: i, name: r.name, opened: r.company_id })}>Edit</button>
                          <button
                            type="button"
                            className="link-button"
                            aria-label={`Remove ${r.name}`}
                            aria-disabled={busy} // as Save: the button keeps the focus while, and after, a Remove fails
                            onClick={async () => {
                              if (busy || !(await act(() => api.removeFlowCompany(flow.flow_id, r.company_id)))) return;
                              setEditing((e) => (e && i < e.row ? { ...e, row: e.row - 1 } : e)); // a form open further down moves up with its row
                              focusRow(neighbour(flow.rows, i)?.company_id);
                            }}
                          >
                            Remove
                          </button>
                        </span>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {n === 0 && <p className="muted">No companies yet. Upload a list, pick a saved universe or add one company.</p>}
          <div className="row-actions argus-flow-actions">
            {identity && (
              <span role="status">
                {identity.text} <a href="#/history">Open identity runs</a>
              </span>
            )}
            {unmatched.length > 0 && (!identity || identity.again) && (
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
            )}
            <button
              type="button"
              disabled={busy || n === 0}
              onClick={() =>
                act(async () => {
                  const f = await api.patchArgusFlow(flow.flow_id, { step: 2 });
                  window.location.hash = flowHref(flow.flow_id, 2);
                  return f;
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
