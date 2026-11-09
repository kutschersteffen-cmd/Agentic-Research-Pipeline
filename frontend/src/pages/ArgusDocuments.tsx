import { useEffect, useState } from "react";
import { api } from "../api/client";
import { FileImg } from "../components/FileLink";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import { continueFilesLabel, previousYear } from "../lib/argusFlow";
import type { ArgusFlow as Flow, FlowFile } from "../types";

type Source = "upload" | "import" | "filings" | "filings_web";
const SOURCES: [Source, string][] = [
  ["upload", "I upload them"],
  ["import", "From the import folder"],
  ["filings", "Official filings"],
  ["filings_web", "Filings + company websites"],
];
const DOC_TYPES: [string, string][] = [
  ["10-K", "Annual report"],
  ["sustainability_report", "Sustainability report"],
  ["DEF-14A", "Proxy statement"],
  ["transition_plan", "Transition plan"],
  ["other", "Other"],
];
const SOURCE_WORDS: Record<FlowFile["source"], string> = { upload: "Uploaded", filings: "Official filing", web: "Company website" };

/** Step 2 of an Argus flow: find or take the companies' documents, check each, keep or remove it in this flow. */
export function ArgusDocuments({ flow, busy, act, onContinue }: {
  flow: Flow;
  busy: boolean;
  act: (fn: () => Promise<Flow | void>) => void;
  onContinue: () => void;
}) {
  const [docType, setDocType] = useState("10-K");
  const [hover, setHover] = useState<string | null>(null);
  const [open, setOpen] = useState<ActiveSource | null>(null);
  const year = flow.reporting_year ?? previousYear(new Date());
  const running = flow.discovery && !["completed", "partially_completed", "failed", "cancelled"].includes(flow.discovery.status);
  const id = flow.flow_id;

  // a discovery run writes its files as it goes: read the flow again until the run ends
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => act(() => api.getArgusFlow(id)), 4000);
    return () => clearInterval(t);
  }, [running, id, act]);

  const go = continueFilesLabel(flow.files);
  const real = flow.files.filter((f) => !f.duplicate_of);
  const rawUrl = (f: FlowFile) => (f.key.startsWith("doc:") ? f.raw_url ?? "" : api.documentRawUrl(f.company_id, f.doc_type, f.filename));

  return (
    <div className={open ? "argus-docs argus-docs-open" : "argus-docs"}>
      <div className="argus-docs-main">
        <section className="card argus-docs-setup" aria-label="Where the documents come from">
          <label className="field-label argus-year">
            Reporting year
            <input
              id="argus-reporting-year"
              type="number"
              min={1990}
              max={2100}
              defaultValue={year}
              key={year}
              disabled={busy}
              onBlur={(e) => {
                const y = Number(e.target.value);
                if (y && y !== year) act(() => api.patchArgusFlow(id, { reporting_year: y }));
              }}
            />
          </label>
          <fieldset className="argus-sources">
            <legend>Documents</legend>
            {SOURCES.map(([value, label]) => (
              <label key={value} className="argus-source">
                <input
                  type="radio"
                  name="argus-source"
                  value={value}
                  checked={flow.source === value}
                  disabled={busy || value === "import"}
                  onChange={() => act(() => api.patchArgusFlow(id, { source: value }))}
                />
                {label}
                {value === "import" && <span className="help-text"> Available once the import folder is set up</span>}
              </label>
            ))}
          </fieldset>
          {(flow.source === "filings" || flow.source === "filings_web") && (
            <div className="row-actions">
              <button type="button" disabled={busy || !!running} onClick={() => act(() => api.findFlowDocuments(id))}>
                Find documents
              </button>
              {flow.discovery && (
                <span role="status" className="muted">
                  {running ? "Searching…" : `Search ${flow.discovery.status.replace("_", " ")}.`} <a href="#/history">Run history</a>
                </span>
              )}
            </div>
          )}
          {flow.source === "upload" && (
            <div className="argus-uploads">
              <label className="field-label">
                Type
                <select id="argus-upload-type" value={docType} onChange={(e) => setDocType(e.target.value)}>
                  {DOC_TYPES.map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </label>
              {flow.companies.map((c) => (
                <label key={c.company_id} className="field-label">
                  {c.name}
                  <input
                    id={`argus-upload-${c.company_id}`}
                    type="file"
                    accept=".pdf,.html,.htm,.txt,.xlsx"
                    disabled={busy}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      e.target.value = "";
                      if (file) act(() => api.uploadFlowDocument(id, c.company_id, docType, file));
                    }}
                  />
                </label>
              ))}
            </div>
          )}
        </section>

        {flow.files.length > 0 && (
          <div className="row-actions">
            <button type="button" className="secondary" disabled={busy} onClick={() => act(() => api.decideFlowFiles(id, { all_that_pass: true }))}>
              Keep all that pass
            </button>
            <button type="button" className="secondary" disabled={busy || real.length === 0} onClick={() => act(() => api.decideFlowFiles(id, { all: true, state: "removed" }))}>
              Remove all
            </button>
          </div>
        )}
        <div className="table-wrap">
          <table className="data-table stack-on-phone" aria-label="Files">
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">File</th>
                <th scope="col">Type</th>
                <th scope="col">Year</th>
                <th scope="col">Source</th>
                <th scope="col">Check</th>
                <th scope="col">In this extraction</th>
              </tr>
            </thead>
            <tbody>
              {flow.files.map((f) => (
                <tr key={f.key} className={f.passes ? undefined : "argus-row-await"}>
                  <td data-label="Company">{f.company_name}</td>
                  <td data-label="File" className="argus-file">
                    {f.duplicate_of ? (
                      f.filename
                    ) : (
                      <button
                        type="button"
                        className="link-button"
                        onMouseEnter={() => setHover(f.key)}
                        onMouseLeave={() => setHover(null)}
                        onFocus={() => setHover(f.key)}
                        onBlur={() => setHover(null)}
                        onClick={() => setOpen({ title: `${f.company_name}: ${f.filename}`, src: rawUrl(f) })}
                      >
                        {f.filename}
                      </button>
                    )}
                    {hover === f.key && f.page_url && (
                      <span className="argus-file-preview">
                        <FileImg url={api.documentPageUrl(rawUrl(f), 1)} alt={`First page of ${f.filename}`} />
                      </span>
                    )}
                  </td>
                  <td data-label="Type">{f.doc_type}</td>
                  <td data-label="Year">{f.year ?? ""}</td>
                  <td data-label="Source">{SOURCE_WORDS[f.source]}</td>
                  <td data-label="Check" className={f.passes ? undefined : "await-text"}>{f.check}</td>
                  <td data-label="In this extraction">
                    {!f.duplicate_of && (
                      <span className="argus-keep">
                        {f.state && <span className={`argus-state argus-state-${f.state}`}>{f.state === "kept" ? "Kept" : "Removed"}</span>}
                        {f.state !== "kept" && (
                          <button type="button" className="link-button" disabled={busy} onClick={() => act(() => api.decideFlowFiles(id, { keys: [f.key], state: "kept" }))}>
                            Keep
                          </button>
                        )}
                        {f.state !== "removed" && (
                          <button type="button" className="link-button" disabled={busy} onClick={() => act(() => api.decideFlowFiles(id, { keys: [f.key], state: "removed" }))}>
                            Remove
                          </button>
                        )}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {flow.files.length === 0 && <p className="muted">No documents yet. Choose where they come from above.</p>}
        <div className="row-actions argus-flow-actions">
          <button type="button" disabled={busy || go.disabled} onClick={onContinue}>
            {go.text}
          </button>
        </div>
      </div>
      {open && <SourcePanel source={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
