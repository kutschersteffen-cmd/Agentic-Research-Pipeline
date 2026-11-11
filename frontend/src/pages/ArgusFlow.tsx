import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { CompanyPicker } from "../components/CompanyPicker";
import { StepBar } from "../components/StepBar";
import { continueLabel, documentsText, extractedBeforeText, flowHref, identifierList } from "../lib/argusFlow";
import { STEPS } from "../lib/argusStart";
import { ArgusDocuments } from "./ArgusDocuments";
import { ArgusExtract } from "./ArgusExtract";
import { ArgusResults } from "./ArgusResults";
import { ArgusSchema } from "./ArgusSchema";
import type { ArgusFlow as Flow } from "../types";


/** #/argus/<flow_id>/<step>: one extraction being set up. The flow lives on the server, so a reload or a teammate's link shows the same step and data. */
export function ArgusFlow({ flowId, step }: { flowId: string; step: number }) {
  const [flow, setFlow] = useState<Flow | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Read again on every step change: a run that finished on step 4 changes what step 3 must show (the repeat
  // warning), and a stale flow let Start through to a 400 that named a list not on screen.
  useEffect(() => {
    api.getArgusFlow(flowId).then(setFlow, (e: Error) => (/not found/i.test(e.message) ? setMissing(true) : setError(e.message)));
  }, [flowId, step]);

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
      setError((e as Error).message);
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
          step === 4 ? <ArgusExtract flow={flow} /> : <ArgusResults flow={flow} />
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
                Identity run started. <a href="#/history">Open identity runs</a>
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
