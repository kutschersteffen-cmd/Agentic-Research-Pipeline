import { useEffect, useState } from "react";
import { api } from "../api/client";
import { FileImg } from "../components/FileLink";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import { filePath, filesLabel, keepPassing, removeAll, SOURCES, visibleFiles } from "../lib/argusFlow";
import { DOC_TYPES } from "../lib/docTypes";
import type { ArgusFlow as Flow, DocType, FlowFile } from "../types";

const TYPE_LABEL = Object.fromEntries(DOC_TYPES) as Record<string, string>;
const SOURCE_LABEL = { upload: "Uploaded", filing: "Official filing", web: "Company website" };
const LOOKING = new Set(["pending", "running"]);

type Act = (fn: () => Promise<Flow | void>) => void;

/** Step 2 of an Argus flow: gather files, see each one's check, keep or remove them. Remove only leaves a file out of this flow. */
export function ArgusDocuments({ flow, busy, act, setFlow, onContinue }: {
  flow: Flow;
  busy: boolean;
  act: Act;
  setFlow: (f: Flow) => void;
  onContinue: () => void;
}) {
  const id = flow.flow_id;
  const [year, setYear] = useState(String(flow.reporting_year));
  const [source, setSource] = useState(flow.doc_source ?? "upload");
  const [company, setCompany] = useState(flow.companies[0]?.company_id ?? "");
  const [docType, setDocType] = useState<DocType>("10-K");
  const [hover, setHover] = useState<string | null>(null);
  const [open, setOpen] = useState<ActiveSource | null>(null);
  const looking = !!flow.discovery && LOOKING.has(flow.discovery.status);
  const files = flow.files;
  // Removed earlier: gone from the list (still on the company); removed in this visit: stays, marked Removed, so it can be undone.
  const [removedAtLoad] = useState(() => new Set(flow.files.filter((f) => f.state === "removed").map((f) => f.key)));
  const [showRemoved, setShowRemoved] = useState(false);
  const shown = visibleFiles(files, removedAtLoad, showRemoved);
  const hidden = files.length - shown.length;
  const kept = files.filter((f) => f.state === "kept").length;

  useEffect(() => {
    if (!looking) return;
    const t = setInterval(() => api.getArgusFlow(id).then(setFlow, () => {}), 3000);
    return () => clearInterval(t);
  }, [looking, id, setFlow]);

  const saveYear = () => {
    const y = Number(year);
    if (Number.isInteger(y) && y !== flow.reporting_year) act(() => api.patchArgusFlow(id, { reporting_year: y }));
  };
  const decide = (decisions: Record<string, "kept" | "removed">) => act(() => api.patchArgusFlow(id, { decisions }));
  const raw = (f: FlowFile) => {
    const p = filePath(f);
    return p && api.documentRawUrl(...p);
  };

  return (
    <>
      <section className="card argus-add" aria-label="Find documents">
        <label className="field-label argus-year">
          Reporting year
          <input
            id="argus-reporting-year"
            type="number"
            min={1990}
            max={2100}
            value={year}
            disabled={busy}
            onChange={(e) => setYear(e.target.value)}
            onBlur={saveYear}
            onKeyDown={(e) => e.key === "Enter" && saveYear()}
          />
        </label>
        <fieldset className="argus-sources">
          <legend>Where do the documents come from?</legend>
          {SOURCES.map(([value, label, enabled]) => (
            <label key={value} className="argus-source">
              <input
                type="radio"
                name="argus-source"
                value={value}
                checked={source === value}
                disabled={!enabled}
                onChange={() => {
                  setSource(value);
                  act(() => api.patchArgusFlow(id, { doc_source: value }));
                }}
              />
              {label}
              {!enabled && <span className="help-text"> Comes with the shared import folder</span>}
            </label>
          ))}
        </fieldset>
        {source === "upload" && (
          <div className="argus-one">
            <fieldset>
              <legend>Upload your documents</legend>
              <label className="field-label">
                Company
                <select id="argus-doc-company" value={company} onChange={(e) => setCompany(e.target.value)} disabled={busy}>
                  {flow.companies.map((c) => (
                    <option key={c.company_id} value={c.company_id}>{c.name}</option>
                  ))}
                </select>
              </label>
              <label className="field-label">
                Type
                <select id="argus-doc-type" value={docType} onChange={(e) => setDocType(e.target.value as DocType)} disabled={busy}>
                  {DOC_TYPES.map(([t, label]) => (
                    <option key={t} value={t}>{label}</option>
                  ))}
                </select>
              </label>
              <label className="field-label">
                Upload PDFs
                <input
                  id="argus-doc-files"
                  type="file"
                  accept=".pdf"
                  multiple
                  disabled={busy || !company}
                  onChange={(e) => {
                    const picked = Array.from(e.target.files ?? []);
                    e.target.value = "";
                    act(async () => {
                      let f: Flow | undefined;
                      for (const file of picked) f = await api.uploadFlowDocument(id, company, docType, file);
                      return f;
                    });
                  }}
                />
              </label>
            </fieldset>
          </div>
        )}
        {(source === "filings" || source === "web") && (
          <div className="row-actions argus-flow-actions">
            <button type="button" className="secondary" disabled={busy || looking} onClick={() => act(() => api.findFlowFiles(id, source === "web"))}>
              {source === "web" ? "Find filings and website documents" : "Find filings"}
            </button>
            {looking && flow.discovery && (
              <span role="status">Looking for files: {flow.discovery.done} of {flow.discovery.total} companies</span>
            )}
          </div>
        )}
      </section>

      <div className={open ? "split-review" : undefined}>
        <div className="split-review-main">
          <div className="table-wrap">
            <table className="data-table stack-on-phone" aria-label="Files">
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col">Company</th>
                  <th scope="col">Type</th>
                  <th scope="col">Year</th>
                  <th scope="col">Source</th>
                  <th scope="col">Check</th>
                  <th scope="col">Decision</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((f) => {
                  const url = raw(f);
                  const pdf = !!url && f.file_name.toLowerCase().endsWith(".pdf");
                  return (
                    <tr key={f.key} className={f.passed ? undefined : "argus-row-await"}>
                      <td data-label="File" className="argus-file">
                        {url ? (
                          <button
                            type="button"
                            className="link-button"
                            onMouseEnter={() => setHover(f.key)}
                            onMouseLeave={() => setHover(null)}
                            onFocus={() => setHover(f.key)}
                            onBlur={() => setHover(null)}
                            onClick={() => {
                              setHover(null);
                              setOpen({ title: f.file_name, src: url });
                            }}
                          >
                            {f.file_name}
                          </button>
                        ) : f.url ? (
                          <a href={f.url} target="_blank" rel="noreferrer">{f.file_name}</a>
                        ) : (
                          f.file_name
                        )}
                        {pdf && hover === f.key && (
                          <div className="argus-preview" role="tooltip">
                            <FileImg url={api.documentPageUrl(url, 1)} alt={`First page of ${f.file_name}`} />
                          </div>
                        )}
                      </td>
                      <td data-label="Company">{flow.companies.find((c) => c.company_id === f.company_id)?.name ?? f.company_id}</td>
                      <td data-label="Type">{TYPE_LABEL[f.doc_type] ?? f.doc_type}</td>
                      <td data-label="Year" className="mono">{f.year ?? ""}</td>
                      <td data-label="Source">{SOURCE_LABEL[f.source]}</td>
                      <td data-label="Check" className={f.passed ? undefined : "await-text"}>{f.check}</td>
                      <td data-label="Decision">
                        {!f.duplicate_of && (
                          <div className="argus-decision">
                            {f.state && <span className="argus-state">{f.state === "kept" ? "Kept" : "Removed"}</span>}
                            {/* only the change a person can still make: a kept file can be removed, a removed one kept */}
                            {f.state !== "kept" && (
                              <button type="button" className="secondary" disabled={busy} onClick={() => decide({ [f.key]: "kept" })}>
                                Keep
                              </button>
                            )}
                            {f.state !== "removed" && (
                              <button type="button" className="secondary" disabled={busy} onClick={() => decide({ [f.key]: "removed" })}>
                                Remove
                              </button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {files.length === 0 && <p className="muted">No files yet. Upload PDFs or look for official filings.</p>}
          {(hidden > 0 || (showRemoved && removedAtLoad.size > 0)) && (
            <button type="button" className="link-button" onClick={() => setShowRemoved(!showRemoved)}>
              {showRemoved ? "Hide removed files" : `Show removed files (${hidden})`}
            </button>
          )}
        </div>
        {open && <SourcePanel source={open} onClose={() => setOpen(null)} />}
      </div>

      <div className="row-actions argus-flow-actions">
        <button type="button" className="secondary" disabled={busy || files.length === 0} onClick={() => decide(keepPassing(files))}>
          Keep all that pass
        </button>
        <button type="button" className="secondary" disabled={busy || files.length === 0} onClick={() => decide(removeAll(files))}>
          Remove all
        </button>
        <button type="button" disabled={busy || kept === 0} onClick={onContinue}>
          {filesLabel(files)}
        </button>
      </div>
    </>
  );
}
